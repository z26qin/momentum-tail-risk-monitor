"""Run the paired Phase 2 market-only versus market-plus-news ablation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

from src.features.gdelt import (
    DEFAULT_CONFIG_PATH,
    PANEL_FILENAME,
    RAW_SUBDIRECTORY,
    load_phase2_config,
)
from src.features.labels import HORIZONS
from src.features.market_features import MODEL_FEATURES
from src.modeling.baselines import _pipeline
from src.modeling.validation import (
    PurgedExpandingWalkForward,
    PurgedSplit,
    make_purged_holdout,
)
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    DEFAULT_RAW_DIR,
    iso_date,
    parse_as_of_date,
    write_parquet,
)


PRIMARY_TEXT_FEATURES = ("attention_max", "narrative_breadth", "tone_min")
MODEL_FEATURES_PHASE2: dict[str, tuple[str, ...]] = {
    "B2c": MODEL_FEATURES,
    "B3": (*MODEL_FEATURES, *PRIMARY_TEXT_FEATURES),
}
PREDICTION_FILENAME = "phase2_oos_predictions.parquet"
RESULT_FILENAME = "phase2_ablation_results.csv"
COVERAGE_FILENAME = "phase2_coverage_report.md"
REVIEW_FILENAME = "phase2_research_review.md"
RANDOM_SEED = 20260724


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(
        temporary,
        index=False,
        lineterminator="\n",
        float_format="%.12g",
    )
    temporary.replace(path)


def _adjacent_episode_ids(event: pd.Series) -> pd.Series:
    event_bool = event.astype(bool)
    onset = event_bool & ~event_bool.shift(1, fill_value=False)
    ids = onset.cumsum().astype("Int64")
    return ids.where(event_bool)


def build_common_sample(
    *,
    horizon: int,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> pd.DataFrame:
    """Build the mature, complete common sample used by both B2c and B3."""

    config = load_phase2_config(config_path)
    start_date = pd.Timestamp(config["source_start_date"])
    market = pd.read_parquet(processed_dir / "market_features.parquet")
    text = pd.read_parquet(processed_dir / PANEL_FILENAME)
    labels = pd.read_parquet(processed_dir / f"momentum_labels_h{horizon}.parquet")
    label_column = f"mom_tail_loss_{horizon}"
    label_columns = ["date", "label_end_date", label_column]

    frame = market.loc[:, ["date", *MODEL_FEATURES]].merge(
        labels.loc[:, label_columns],
        on="date",
        how="inner",
        validate="one_to_one",
    )
    frame = frame.merge(text, on="date", how="inner", validate="one_to_one")
    frame.rename(columns={label_column: "event"}, inplace=True)

    mature = frame["event"].notna() & frame["label_end_date"].notna()
    mature &= frame["label_end_date"].le(as_of_date)
    market_complete = frame.loc[:, MODEL_FEATURES].notna().all(axis=1)
    text_complete = (
        frame["text_history_ready"].astype(bool)
        & ~frame["unresolved_api_failure"].astype(bool)
        & frame.loc[:, PRIMARY_TEXT_FEATURES].notna().all(axis=1)
    )
    frame = frame.loc[
        frame["date"].ge(start_date) & mature & market_complete & text_complete
    ].copy()
    frame["event"] = frame["event"].astype(bool)
    frame.sort_values("date", inplace=True)
    frame.reset_index(drop=True, inplace=True)
    if frame.empty:
        raise ValueError(f"No common Phase 2 sample for horizon {horizon}")
    if frame["date"].duplicated().any():
        raise AssertionError("Common sample contains duplicate dates")
    if frame["label_end_date"].max() > as_of_date:
        raise AssertionError("Common sample includes an immature label")
    frame["phase2_episode_id"] = _adjacent_episode_ids(frame["event"])
    # The Phase 1 splitter validates this conventional column name.
    frame["event_episode_id"] = frame["phase2_episode_id"]
    return frame


def _fit_probabilities(
    train: pd.DataFrame,
    test: pd.DataFrame,
    features: Iterable[str],
) -> np.ndarray:
    feature_names = list(features)
    model = _pipeline()
    model.fit(
        train.loc[:, feature_names].astype(float),
        train["event"].astype(int),
    )
    return model.predict_proba(test.loc[:, feature_names].astype(float))[:, 1]


def _paired_prediction_frame(
    *,
    frame: pd.DataFrame,
    split: PurgedSplit,
    scope: str,
    horizon: int,
) -> pd.DataFrame:
    train = frame.loc[split.train_index]
    test = frame.loc[split.test_index]
    if train["event"].nunique() != 2:
        raise ValueError(f"{split.split_id} training sample has only one class")

    b2c_test_index = test.index.copy()
    b2c_probability = _fit_probabilities(train, test, MODEL_FEATURES_PHASE2["B2c"])
    b3_test_index = test.index.copy()
    b3_probability = _fit_probabilities(train, test, MODEL_FEATURES_PHASE2["B3"])
    if not b2c_test_index.equals(b3_test_index):
        raise AssertionError("B2c and B3 test indices differ")

    result = test.loc[
        :,
        [
            "date",
            "label_end_date",
            "event",
            "phase2_episode_id",
            *PRIMARY_TEXT_FEATURES,
        ],
    ].copy()
    result.insert(0, "scope", scope)
    result.insert(1, "horizon_days", horizon)
    result.insert(2, "split_id", split.split_id)
    result["b2c_probability"] = b2c_probability
    result["b3_probability"] = b3_probability
    result["paired_test_index_verified"] = True
    return result


def _safe_auc(metric: str, event: np.ndarray, probability: np.ndarray) -> float:
    if np.unique(event).size < 2:
        return float("nan")
    if metric == "pr":
        return float(average_precision_score(event, probability))
    return float(roc_auc_score(event, probability))


def _probability_loss(event: np.ndarray, probability: np.ndarray) -> np.ndarray:
    clipped = np.clip(probability, 1e-12, 1.0 - 1e-12)
    return -(event * np.log(clipped) + (1 - event) * np.log(1.0 - clipped))


def moving_block_bootstrap_mean_ci(
    paired_difference: np.ndarray,
    *,
    block_length: int,
    replications: int,
    seed: int = RANDOM_SEED,
) -> tuple[float, float]:
    """Return a percentile CI for the mean using circular moving blocks."""

    values = np.asarray(paired_difference, dtype=float)
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("Bootstrap input must be a nonempty vector")
    if block_length <= 0 or replications <= 0:
        raise ValueError("Bootstrap settings must be positive")
    rng = np.random.default_rng(seed)
    n = len(values)
    blocks_needed = int(np.ceil(n / block_length))
    estimates = np.empty(replications, dtype=float)
    offsets = np.arange(block_length)
    for replication in range(replications):
        starts = rng.integers(0, n, size=blocks_needed)
        positions = (starts[:, None] + offsets[None, :]) % n
        sample = values[positions.ravel()[:n]]
        estimates[replication] = sample.mean()
    lower, upper = np.quantile(estimates, [0.025, 0.975])
    return float(lower), float(upper)


def _episode_diagnostic(
    predictions: pd.DataFrame,
    *,
    probability_column: str,
    lookback: int,
) -> dict[str, float | int]:
    ordered = predictions.sort_values("date").reset_index(drop=True)
    threshold = float(ordered[probability_column].quantile(0.90))
    event_rows = ordered.loc[ordered["event"]]
    episode_onsets = event_rows.groupby("phase2_episode_id", sort=True)["date"].min()
    captured = 0
    leads: list[int] = []
    evaluable = 0
    for onset in episode_onsets:
        onset_positions = ordered.index[ordered["date"].eq(onset)]
        if len(onset_positions) == 0:
            continue
        onset_position = int(onset_positions[0])
        warning_window = ordered.iloc[max(0, onset_position - lookback) : onset_position]
        if warning_window.empty:
            continue
        evaluable += 1
        alerts = warning_window.index[
            warning_window[probability_column].ge(threshold)
        ]
        if len(alerts):
            captured += 1
            leads.append(onset_position - int(alerts.max()))
    return {
        "episode_capture": captured / evaluable if evaluable else float("nan"),
        "episodes_captured": captured,
        "episodes_evaluable": evaluable,
        "approximate_lead_time_trading_days": (
            float(np.mean(leads)) if leads else float("nan")
        ),
        "retrospective_top_decile_threshold": threshold,
    }


def _metric_rows(
    predictions: pd.DataFrame,
    *,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    event = predictions["event"].astype(int).to_numpy()
    block_length = int(config["model_specification"]["bootstrap_block_length"])
    replications = int(config["model_specification"]["bootstrap_replications"])
    lookback = int(
        config["model_specification"]["episode_warning_lookback_trading_days"]
    )
    rows: list[dict[str, Any]] = []
    metric_by_model: dict[str, dict[str, Any]] = {}
    for model, probability_column in (
        ("B2c", "b2c_probability"),
        ("B3", "b3_probability"),
    ):
        probability = predictions[probability_column].to_numpy()
        episode = _episode_diagnostic(
            predictions,
            probability_column=probability_column,
            lookback=lookback,
        )
        metrics: dict[str, Any] = {
            "log_loss": float(log_loss(event, probability, labels=[0, 1])),
            "brier_score": float(brier_score_loss(event, probability)),
            "pr_auc": _safe_auc("pr", event, probability),
            "roc_auc": _safe_auc("roc", event, probability),
            **episode,
        }
        metric_by_model[model] = metrics
        rows.append({"model": model, **metrics})

    b2_loss = _probability_loss(event, predictions["b2c_probability"].to_numpy())
    b3_loss = _probability_loss(event, predictions["b3_probability"].to_numpy())
    lower, upper = moving_block_bootstrap_mean_ci(
        b3_loss - b2_loss,
        block_length=block_length,
        replications=replications,
    )
    difference = {
        key: metric_by_model["B3"][key] - metric_by_model["B2c"][key]
        for key in ("log_loss", "brier_score", "pr_auc", "roc_auc", "episode_capture")
    }
    rows.append(
        {
            "model": "difference_B3_minus_B2c",
            **difference,
            "episodes_captured": np.nan,
            "episodes_evaluable": metric_by_model["B3"]["episodes_evaluable"],
            "approximate_lead_time_trading_days": np.nan,
            "retrospective_top_decile_threshold": np.nan,
            "log_loss_difference_ci_lower_95": lower,
            "log_loss_difference_ci_upper_95": upper,
            "bootstrap_block_length": block_length,
            "bootstrap_replications": replications,
        }
    )
    return rows


def _development_splits(
    frame: pd.DataFrame,
    *,
    config: dict[str, Any],
) -> list[PurgedSplit]:
    settings = config["model_specification"]
    splitter = PurgedExpandingWalkForward(
        initial_train_years=int(settings["initial_train_years"]),
        test_block_years=int(settings["test_block_years"]),
        step_years=int(settings["step_years"]),
    )
    return list(
        splitter.split(
            frame,
            model_start=pd.Timestamp(config["source_start_date"]),
            development_end=pd.Timestamp(config["development_end_exclusive"]),
        )
    )


def run_phase2_ablation(
    *,
    as_of_date: pd.Timestamp,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[int, pd.DataFrame]]:
    """Fit paired development folds and one frozen final-test split."""

    config = load_phase2_config(config_path)
    if as_of_date != pd.Timestamp(config["as_of_date"]):
        raise ValueError("Requested as-of date differs from frozen Phase 2 config")
    holdout_start = pd.Timestamp(config["final_test_start"])
    prediction_parts: list[pd.DataFrame] = []
    common_samples: dict[int, pd.DataFrame] = {}

    for horizon in HORIZONS:
        frame = build_common_sample(
            horizon=horizon,
            as_of_date=as_of_date,
            processed_dir=processed_dir,
            config_path=config_path,
        )
        common_samples[horizon] = frame
        development_frame = frame.loc[frame["date"].lt(holdout_start)].copy()
        development_frame.reset_index(drop=True, inplace=True)
        for split in _development_splits(development_frame, config=config):
            prediction_parts.append(
                _paired_prediction_frame(
                    frame=development_frame,
                    split=split,
                    scope="development",
                    horizon=horizon,
                )
            )

        holdout_split = make_purged_holdout(
            frame,
            model_start=pd.Timestamp(config["source_start_date"]),
            holdout_start=holdout_start,
            as_of_date=as_of_date,
        )
        prediction_parts.append(
            _paired_prediction_frame(
                frame=frame,
                split=holdout_split,
                scope="final_test",
                horizon=horizon,
            )
        )

    predictions = pd.concat(prediction_parts, ignore_index=True)
    if not predictions["paired_test_index_verified"].all():
        raise AssertionError("At least one paired prediction row was not verified")
    write_parquet(predictions, output_dir / PREDICTION_FILENAME)

    result_rows: list[dict[str, Any]] = []
    for (scope, horizon), group in predictions.groupby(
        ["scope", "horizon_days"], sort=True
    ):
        for row in _metric_rows(group, config=config):
            result_rows.append(
                {
                    "scope": scope,
                    "horizon_days": int(horizon),
                    "rows": len(group),
                    "event_days": int(group["event"].sum()),
                    "event_rate": float(group["event"].mean()),
                    **row,
                }
            )
    results = pd.DataFrame(result_rows)
    _write_csv(results, output_dir / RESULT_FILENAME)
    return predictions, results, common_samples


def _format_percent(value: float) -> str:
    return "NA" if pd.isna(value) else f"{100 * value:.1f}%"


def _format_number(value: float, digits: int = 4) -> str:
    return "NA" if pd.isna(value) else f"{value:.{digits}f}"


def write_coverage_report(
    *,
    panel: pd.DataFrame,
    title_samples: dict[str, list[str]],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    config = load_phase2_config(config_path)
    query_names = list(config["queries"])
    lines = [
        "# Phase 2 GDELT coverage report",
        "",
        f"- Trading-date coverage: {iso_date(panel['date'].min())} through {iso_date(panel['date'].max())} ({len(panel):,} rows).",
        f"- Rows with complete prior-only 126-day volume normalization history: {int(panel['text_history_ready'].sum()):,}.",
        f"- Trading dates with an unresolved GDELT-wide source gap: {int(panel['unresolved_api_failure'].sum()):,}; these rows are excluded from both models rather than encoded as zero news.",
        "- Timing rule: a UTC calendar-day bucket is attached to the first US trading close strictly after that calendar date. Friday through Sunday therefore pool into Monday when Monday is open; holiday buckets roll to the next open date.",
        "- Timestamp assumption: DOC 2.0 daily timeline labels identify UTC calendar buckets. A bucket is treated as complete only at 00:00 UTC on the following calendar day, which precludes same-day-close use.",
        "- Zero matching articles are recorded as a zero count/volume and undefined tone. A request or parse failure sets an explicit failure state and is never converted to zero.",
        "- Every z-score requires a full 126-row calendar history. Volume uses at least 101 observed prior days (80% of the window) so a documented vendor outage does not erase otherwise usable later dates; tone uses at least 20 observed-tone days because zero-match tone is undefined.",
        "",
        "## Query coverage",
        "",
        "| Query | First normalized date | Volume missing | Tone-z missing | Zero-match trading dates |",
        "|---|---:|---:|---:|---:|",
    ]
    for query_name in query_names:
        stem = query_name.lower()
        normalized = panel.loc[panel[f"{stem}_vol_z"].notna(), "date"]
        first = iso_date(normalized.iloc[0]) if len(normalized) else "NA"
        lines.append(
            f"| {query_name} | {first} | "
            f"{_format_percent(panel[f'{stem}_vol_z'].isna().mean())} | "
            f"{_format_percent(panel[f'{stem}_tone_z'].isna().mean())} | "
            f"{_format_percent(panel[f'{stem}_zero_match'].mean())} |"
        )

    compact = [
        *[f"{name.lower()}_vol_z" for name in query_names],
        *[f"{name.lower()}_tone_z" for name in query_names],
        *PRIMARY_TEXT_FEATURES,
    ]
    description = panel[compact].describe(percentiles=[0.05, 0.5, 0.95]).T
    lines.extend(
        [
            "",
            "## Feature distributions",
            "",
            "| Feature | Count | Mean | Std | 5% | Median | 95% |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for feature, row in description.iterrows():
        lines.append(
            f"| {feature} | {int(row['count'])} | {_format_number(row['mean'], 3)} | "
            f"{_format_number(row['std'], 3)} | {_format_number(row['5%'], 3)} | "
            f"{_format_number(row['50%'], 3)} | {_format_number(row['95%'], 3)} |"
        )

    correlation = panel[compact].corr()
    pairs: list[tuple[float, str, str]] = []
    for left_position, left in enumerate(compact):
        for right in compact[left_position + 1 :]:
            value = correlation.loc[left, right]
            if pd.notna(value):
                pairs.append((abs(float(value)), left, right))
    pairs.sort(reverse=True)
    lines.extend(
        [
            "",
            "## Largest absolute feature correlations",
            "",
            "| Feature 1 | Feature 2 | Correlation |",
            "|---|---|---:|",
        ]
    )
    for _, left, right in pairs[:12]:
        lines.append(f"| {left} | {right} | {correlation.loc[left, right]:.3f} |")

    lines.extend(["", "## Label-blind title sanity check", ""])
    for query_name in query_names:
        lines.append(f"### {query_name}")
        lines.append("")
        lines.append(
            f"Query: `{config['queries'][query_name]['query']}`"
        )
        lines.append("")
        sample = title_samples.get(query_name, [])
        if sample:
            for title in sample[:5]:
                lines.append(f"- {title}")
        else:
            lines.append("- Title sample was not refreshed in this run; see the cached raw ArtList response.")
        lines.append("")
        lines.append(
            f"Sanity decision: {config['queries'][query_name]['semantic_check']}"
        )
        lines.append("")

    (output_dir / COVERAGE_FILENAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _result_row(
    results: pd.DataFrame,
    *,
    scope: str,
    horizon: int,
    model: str,
) -> pd.Series:
    match = results.loc[
        results["scope"].eq(scope)
        & results["horizon_days"].eq(horizon)
        & results["model"].eq(model)
    ]
    if len(match) != 1:
        raise ValueError(f"Expected one result row for {scope}/{horizon}/{model}")
    return match.iloc[0]


def _example_diagnostics(
    predictions: pd.DataFrame,
    *,
    scope: str,
    horizon: int,
) -> tuple[pd.Series | None, pd.Series | None]:
    subset = predictions.loc[
        predictions["scope"].eq(scope)
        & predictions["horizon_days"].eq(horizon)
    ].sort_values("date").reset_index(drop=True)
    if subset.empty:
        return None, None
    subset["increment"] = subset["b3_probability"] - subset["b2c_probability"]

    useful_candidates: list[pd.Series] = []
    for _, episode in subset.loc[subset["event"]].groupby("phase2_episode_id"):
        onset = episode["date"].min()
        onset_position = int(subset.index[subset["date"].eq(onset)][0])
        window = subset.iloc[max(0, onset_position - 10) : onset_position]
        if not window.empty:
            useful_candidates.append(window.loc[window["increment"].idxmax()])
    useful = (
        max(useful_candidates, key=lambda row: float(row["increment"]))
        if useful_candidates
        else None
    )

    future_event = (
        subset["event"]
        .astype(int)
        .iloc[::-1]
        .rolling(10, min_periods=1)
        .max()
        .iloc[::-1]
        .shift(-1)
        .fillna(0)
        .astype(bool)
    )
    false_candidates = subset.loc[~future_event & ~subset["event"]]
    false_positive = (
        false_candidates.loc[false_candidates["increment"].idxmax()]
        if not false_candidates.empty
        else None
    )
    return useful, false_positive


def _conclusion(results: pd.DataFrame) -> tuple[str, str]:
    development = _result_row(
        results,
        scope="development",
        horizon=20,
        model="difference_B3_minus_B2c",
    )
    final = _result_row(
        results,
        scope="final_test",
        horizon=20,
        model="difference_B3_minus_B2c",
    )
    dev_delta = float(development["log_loss"])
    final_delta = float(final["log_loss"])
    dev_upper = float(development["log_loss_difference_ci_upper_95"])
    if dev_delta < 0 and dev_upper < 0 and final_delta < 0:
        return (
            "positive",
            "The compact aggregate narrative specification added consistent incremental probability information beyond the common-sample market model, though the small number of episodes still limits confidence.",
        )
    if dev_delta > 0 and final_delta > 0:
        return (
            "adverse",
            "The compact aggregate narrative specification worsened probability performance in both development and the final test relative to the common-sample market model.",
        )
    if dev_delta < 0 or final_delta < 0:
        return (
            "mixed",
            "The compact aggregate narrative specification showed some incremental signal, but the probability and/or episode evidence was not consistent enough to claim reliable value.",
        )
    return (
        "null",
        "The tested aggregate narrative specification did not add reliable incremental value beyond the market-state model.",
    )


def write_research_review(
    *,
    predictions: pd.DataFrame,
    results: pd.DataFrame,
    common_samples: dict[int, pd.DataFrame],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> None:
    conclusion_label, conclusion_text = _conclusion(results)
    lines = [
        "# Phase 2 research review",
        "",
        "## 1. Research question",
        "",
        "Does aggregate, timestamped public-news narrative add incremental early-warning value beyond the Phase 1 market-state model on an identical common sample?",
        "",
        "## 2. Economic intuition",
        "",
        "Panic and broad risk-off attention can rise before forced exposure reduction, while policy or liquidity surprises can trigger regime changes. Rotation, crowding, deleveraging, and squeeze narratives are especially relevant to momentum because reversals often combine falling recent winners with sharp rebounds in prior losers. Aggregate text can nevertheless fail: it is generic, duplicated across outlets, contemporaneous rather than leading, and only loosely connected to the specific holdings driving a momentum portfolio.",
        "",
        "## 3. Data design",
        "",
        "GDELT UTC calendar buckets are attached only to the first US trading close strictly after the bucket date. Weekend and holiday observations pool into the next open date. Volume uses pooled matched counts divided by pooled monitored-news counts; tone is matched-count weighted. Zero matches remain zero volume with undefined tone, while failed requests remain explicit failures and are excluded. Every z-score uses a 126-trading-row window shifted by one row, so the current observation never normalizes itself.",
        "",
        "B2c refits the exact 24 Phase 1 B2 market features on the Phase 2 common sample. B3 adds only `attention_max`, `narrative_breadth`, and `tone_min`. Both models use identical purged splits and training-fold-only median imputation and scaling. The model class and L2 regularization are unchanged.",
        "",
        "Governance note: an initial dry run was rejected during calendar audit because a 120/126 observed-volume requirement delayed the usable final-test start until December 2025 and fold anchoring omitted the last development year. Before accepting any result, the coverage rule was refrozen at 101/126 observed prior days (80%) and folds were anchored to the fixed 2017-01-01 research start. This correction used only vendor coverage and dates, not labels, but the final test is not perfectly pristine because incomplete-sample metrics had been displayed.",
        "",
        f"After excluding unresolved vendor-gap rows, the accepted final-test common sample begins on {iso_date(predictions.loc[predictions['scope'].eq('final_test'), 'date'].min())}.",
        "",
        f"The mature common sample ends on {iso_date(common_samples[20]['date'].max())} for h=20 and {iso_date(common_samples[5]['date'].max())} for h=5.",
        "",
        "## 4. Results",
        "",
        "Negative differences are better for log loss and Brier score; positive differences are better for PR-AUC and episode capture. Episode capture is a retrospective top-decile warning diagnostic over the prior 10 trading dates, not an optimized rule.",
        "",
        "| Scope | Horizon | Model | Log loss | Brier | PR-AUC | ROC-AUC | Episode capture |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for scope in ("development", "final_test"):
        for horizon in (20, 5):
            for model in ("B2c", "B3", "difference_B3_minus_B2c"):
                row = _result_row(
                    results, scope=scope, horizon=horizon, model=model
                )
                lines.append(
                    f"| {scope} | {horizon} | {model} | "
                    f"{_format_number(row['log_loss'])} | "
                    f"{_format_number(row['brier_score'])} | "
                    f"{_format_number(row['pr_auc'])} | "
                    f"{_format_number(row['roc_auc'])} | "
                    f"{_format_percent(row['episode_capture'])} |"
                )
            difference = _result_row(
                results,
                scope=scope,
                horizon=horizon,
                model="difference_B3_minus_B2c",
            )
            lines.append(
                f"| {scope} | {horizon} | paired log-loss 95% block-bootstrap CI | "
                f"[{_format_number(difference['log_loss_difference_ci_lower_95'])}, "
                f"{_format_number(difference['log_loss_difference_ci_upper_95'])}] |  |  |  |  |"
            )

    lines.extend(
        [
            "",
            "## 5. Interpretation",
            "",
            "Log loss and Brier score assess probability quality and calibration; PR-AUC and ROC-AUC assess event ranking; the episode diagnostic asks whether a PM would have seen an elevated score before an episode. These are different claims. A small improvement in one metric is not treated as economically meaningful unless it is directionally supported by the paired uncertainty estimate, final-test behavior, and episode evidence.",
            "",
            "The primary h=20 final test contains no positive event days. Its log loss still measures the cost of assigned probabilities on non-event days, but PR-AUC, ROC-AUC, and episode capture are not estimable, so it cannot validate early-warning usefulness.",
            "",
            "## 6. Two examples",
            "",
        ]
    )
    useful, false_positive = _example_diagnostics(
        predictions, scope="final_test", horizon=20
    )
    useful_horizon = 20
    if useful is None:
        useful, _ = _example_diagnostics(
            predictions, scope="final_test", horizon=5
        )
        useful_horizon = 5
    if useful is not None:
        lines.extend(
            [
                "### Useful warning candidate",
                "",
                f"For h={useful_horizon}, on {iso_date(useful['date'])}, B2c was {_format_percent(useful['b2c_probability'])} and B3 was {_format_percent(useful['b3_probability'])}. "
                f"The text increment coincided with `attention_max={useful['attention_max']:.2f}`, "
                f"`narrative_breadth={int(useful['narrative_breadth'])}`, and `tone_min={useful['tone_min']:.2f}` before a labelled episode.",
                "This is a retrospective illustration, and the benign-looking aggregate text values make it weak economic evidence despite the elevated B3 score.",
                "",
            ]
        )
    else:
        lines.extend(
            ["### Useful warning candidate", "", "No evaluable pre-episode example was available in the final test.", ""]
        )
    if false_positive is not None:
        lines.extend(
            [
                "### False-positive candidate",
                "",
                f"On {iso_date(false_positive['date'])}, B2c was {_format_percent(false_positive['b2c_probability'])} and B3 was {_format_percent(false_positive['b3_probability'])}, "
                f"with `attention_max={false_positive['attention_max']:.2f}`, "
                f"`narrative_breadth={int(false_positive['narrative_breadth'])}`, and `tone_min={false_positive['tone_min']:.2f}`, "
                "but no labelled event followed in the next 10 trading rows.",
                "",
            ]
        )
    else:
        lines.extend(
            ["### False-positive candidate", "", "No evaluable false-positive example was available.", ""]
        )

    lines.extend(
        [
            "## 7. Conclusion",
            "",
            f"**{conclusion_label}.** {conclusion_text}",
            "",
            "This result concerns only the tested aggregate specification. It does not establish that article-level retrieval, RAG, embeddings, or a larger text model would work.",
            "",
            "## 8. PM use",
            "",
            "The prototype is best viewed as a secondary risk-review trigger that asks the PM to inspect momentum exposure, crowding, and squeeze-sensitive positions—not as an automatic trade signal.",
            "",
        ]
    )
    (output_dir / REVIEW_FILENAME).write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    arguments = parser.parse_args()
    as_of_date = parse_as_of_date(arguments.as_of_date)
    predictions, results, common_samples = run_phase2_ablation(
        as_of_date=as_of_date,
        config_path=arguments.config,
    )
    panel = pd.read_parquet(DEFAULT_PROCESSED_DIR / PANEL_FILENAME)
    raw_dir = DEFAULT_RAW_DIR / RAW_SUBDIRECTORY
    title_samples: dict[str, list[str]] = {}
    config = load_phase2_config(arguments.config)
    for query_name in config["queries"]:
        path = raw_dir / f"{query_name.lower()}_titles.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            title_samples[query_name] = [
                str(article.get("title", "")).strip()
                for article in payload.get("articles", [])
                if str(article.get("title", "")).strip()
            ]
    write_coverage_report(
        panel=panel,
        title_samples=title_samples,
        config_path=arguments.config,
    )
    write_research_review(
        predictions=predictions,
        results=results,
        common_samples=common_samples,
    )
    print(
        results.loc[
            results["model"].eq("difference_B3_minus_B2c"),
            [
                "scope",
                "horizon_days",
                "log_loss",
                "log_loss_difference_ci_lower_95",
                "log_loss_difference_ci_upper_95",
                "pr_auc",
                "episode_capture",
            ],
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
