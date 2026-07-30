"""Portfolio concentration diagnostics for the Phase 2 momentum portfolio.

The functions in this module do not change portfolio construction. They
reconstruct the published month-start weights and their within-month drift so
that exposure and constituent P&L concentration can be inspected separately.
All historical sector results inherit the repository's current-classification
proxy limitation.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd


CONSTITUENT_RETURN_COLUMNS = (
    "date",
    "formation_date",
    "effective_month",
    "symbol",
    "leg",
    "target_weight",
    "beginning_abs_weight",
    "signed_beginning_weight",
    "asset_return",
    "signed_contribution",
    "loss_contribution",
    "contribution_complete",
)

CONCENTRATION_HISTORY_COLUMNS = (
    "date",
    "formation_date",
    "effective_month",
    "effective_bets_abs_exposure",
    "top3_abs_exposure_share",
    "top5_abs_exposure_share",
    "top3_abs_contribution_share",
    "top5_abs_contribution_share",
    "top3_loss_contribution_share",
    "top5_loss_contribution_share",
    "sector_hhi",
    "top_sector_exposure_share",
    "top_two_sector_exposure_share",
    "missing_sector_exposure_share",
    "top5_exposure_loss_overlap_share",
    "exposure_loss_correlation",
    "classification_status",
    "survivorship_bias",
)

REBALANCE_DIAGNOSTIC_COLUMNS = (
    "formation_date",
    "leg",
    "holding_count",
    "overlap_count",
    "overlap_share",
    "turnover_share",
    "average_holding_rebalances",
    "rank_persistence",
)


def _finite_vector(values: Iterable[float]) -> np.ndarray | None:
    """Return a finite numeric vector, or ``None`` for incomplete input."""

    series = pd.to_numeric(pd.Series(list(values), dtype="object"), errors="coerce")
    if series.empty or series.isna().any():
        return None
    vector = series.to_numpy(dtype="float64")
    if not np.isfinite(vector).all():
        return None
    return vector


def effective_bets(exposures: Iterable[float]) -> float | None:
    """Calculate gross-normalized effective bets from signed or unsigned input.

    The input need not be pre-normalized. Absolute exposures are divided by
    total gross exposure before applying ``1 / sum(weight**2)``. Missing,
    non-finite, or all-zero input is unavailable.
    """

    vector = _finite_vector(exposures)
    if vector is None:
        return None
    gross = float(np.abs(vector).sum())
    if gross <= 0.0:
        return None
    normalized = np.abs(vector) / gross
    return float(1.0 / np.square(normalized).sum())


def top_absolute_share(
    values: Iterable[float],
    *,
    top_n: int,
) -> float | None:
    """Return the top-``n`` share of total absolute magnitude."""

    if top_n < 1:
        raise ValueError("top_n must be positive")
    vector = _finite_vector(values)
    if vector is None:
        return None
    magnitudes = np.abs(vector)
    denominator = float(magnitudes.sum())
    if denominator <= 0.0:
        return None
    selected = np.sort(magnitudes)[-min(top_n, len(magnitudes)) :]
    return float(selected.sum() / denominator)


def sector_concentration(
    exposures: Iterable[float],
    sectors: Sequence[Any],
) -> dict[str, float | str | None]:
    """Summarize absolute exposure by current sector classification.

    Missing sectors remain an explicit ``unclassified`` bucket and their
    exposure share is returned separately.
    """

    exposure_vector = _finite_vector(exposures)
    sector_values = list(sectors)
    if exposure_vector is None:
        return {
            "sector_hhi": None,
            "top_sector": None,
            "top_sector_exposure_share": None,
            "top_two_sector_exposure_share": None,
            "missing_sector_exposure_share": None,
        }
    if len(exposure_vector) != len(sector_values):
        raise ValueError("exposures and sectors must have equal length")
    gross = float(np.abs(exposure_vector).sum())
    if gross <= 0.0:
        return {
            "sector_hhi": None,
            "top_sector": None,
            "top_sector_exposure_share": None,
            "top_two_sector_exposure_share": None,
            "missing_sector_exposure_share": None,
        }

    labels = pd.Series(sector_values, dtype="object")
    missing = labels.isna() | labels.astype(str).str.strip().eq("")
    labels = labels.where(~missing, "unclassified").astype(str)
    frame = pd.DataFrame(
        {
            "sector": labels,
            "exposure": np.abs(exposure_vector) / gross,
        }
    )
    shares = (
        frame.groupby("sector", sort=True)["exposure"]
        .sum()
        .sort_values(ascending=False)
    )
    return {
        "sector_hhi": float(np.square(shares.to_numpy()).sum()),
        "top_sector": str(shares.index[0]),
        "top_sector_exposure_share": float(shares.iloc[0]),
        "top_two_sector_exposure_share": float(shares.iloc[:2].sum()),
        "missing_sector_exposure_share": float(
            frame.loc[frame["sector"].eq("unclassified"), "exposure"].sum()
        ),
    }


def holding_overlap(
    current_symbols: Iterable[str],
    previous_symbols: Iterable[str],
) -> tuple[int, float | None]:
    """Return overlap count and share using the current basket denominator."""

    current = {str(value) for value in current_symbols}
    previous = {str(value) for value in previous_symbols}
    if not current:
        return 0, None
    count = len(current & previous)
    return count, float(count / len(current))


def _last_month_is_complete(last_date: pd.Timestamp) -> bool:
    normalized = pd.Timestamp(last_date).normalize()
    return bool(
        normalized.is_month_end
        or normalized == normalized + pd.offsets.BMonthEnd(0)
    )


def _validated_price_returns(prices: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "symbol", "close_total_return_adjusted"}
    missing = sorted(required - set(prices.columns))
    if missing:
        raise KeyError(f"prices missing required columns: {missing}")
    frame = prices.loc[:, sorted(required)].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str)
    frame["close_total_return_adjusted"] = pd.to_numeric(
        frame["close_total_return_adjusted"],
        errors="coerce",
    )
    frame = frame.dropna(subset=["date", "symbol", "close_total_return_adjusted"])
    frame = frame.loc[frame["close_total_return_adjusted"].gt(0)].copy()
    frame = frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    if frame.duplicated(["symbol", "date"]).any():
        raise ValueError("prices contain duplicate symbol/date observations")
    frame["asset_return"] = frame.groupby("symbol", sort=False)[
        "close_total_return_adjusted"
    ].pct_change(fill_method=None)
    frame["effective_month"] = frame["date"].dt.to_period("M")
    return frame


def _validated_holdings(holdings: pd.DataFrame) -> pd.DataFrame:
    required = {
        "formation_date",
        "effective_month",
        "symbol",
        "leg",
        "weight",
    }
    missing = sorted(required - set(holdings.columns))
    if missing:
        raise KeyError(f"holdings missing required columns: {missing}")
    frame = holdings.loc[:, sorted(required)].copy()
    frame["formation_date"] = pd.to_datetime(frame["formation_date"]).dt.normalize()
    frame["effective_month"] = frame["effective_month"].map(
        lambda value: pd.Period(value, freq="M")
    )
    frame["symbol"] = frame["symbol"].astype(str)
    frame["weight"] = pd.to_numeric(frame["weight"], errors="raise")
    if frame.empty:
        raise ValueError("holdings cannot be empty")
    if frame.duplicated(["formation_date", "symbol"]).any():
        raise ValueError("holdings contain duplicate formation/symbol rows")
    if not set(frame["leg"]).issubset({"long", "short"}):
        raise ValueError("holdings legs must be long or short")
    expected_sign = np.where(frame["leg"].eq("long"), 1.0, -1.0)
    if not np.equal(np.sign(frame["weight"]), expected_sign).all():
        raise ValueError("holding weight signs do not agree with leg labels")
    return frame


def build_constituent_return_history(
    prices: pd.DataFrame,
    holdings: pd.DataFrame,
    *,
    exclude_incomplete_last_month: bool = True,
) -> pd.DataFrame:
    """Reconstruct constituent contributions under the Phase 2 drift rule.

    Each leg starts its effective month at gross exposure one. Beginning-of-day
    weights then drift with relative wealth. If any constituent return is
    missing, every contribution in that leg is unavailable from that date
    through month-end, matching ``build_portfolio_returns``.
    """

    price_frame = _validated_price_returns(prices)
    holding_frame = _validated_holdings(holdings)
    if exclude_incomplete_last_month:
        last_date = price_frame["date"].max()
        if not _last_month_is_complete(last_date):
            incomplete = last_date.to_period("M")
            price_frame = price_frame.loc[
                price_frame["effective_month"].ne(incomplete)
            ].copy()

    active = holding_frame.rename(columns={"weight": "target_weight"})
    calendar = price_frame.loc[:, ["date", "effective_month"]].drop_duplicates()
    expected = calendar.merge(
        active,
        on="effective_month",
        how="inner",
        validate="many_to_many",
    ).merge(
        price_frame.loc[:, ["date", "symbol", "asset_return"]],
        on=["date", "symbol"],
        how="left",
        validate="many_to_one",
    )

    records: list[pd.DataFrame] = []
    grouping = ["formation_date", "effective_month", "leg"]
    for keys, group in expected.groupby(grouping, sort=True):
        formation_date, effective_month, leg = keys
        symbols = sorted(group["symbol"].unique())
        returns = group.pivot(
            index="date",
            columns="symbol",
            values="asset_return",
        ).reindex(columns=symbols)
        targets = (
            active.loc[
                active["effective_month"].eq(effective_month)
                & active["leg"].eq(leg),
                ["symbol", "target_weight"],
            ]
            .set_index("symbol")["target_weight"]
            .abs()
            .reindex(symbols)
        )
        if targets.isna().any() or not np.isclose(targets.sum(), 1.0):
            raise ValueError(
                f"{effective_month} {leg} absolute target weights must sum to one"
            )

        complete_today = returns.notna().all(axis=1)
        complete_through_today = complete_today.cummin()
        prior_relative_wealth = (
            (1.0 + returns).cumprod(skipna=False).shift(1).fillna(1.0)
        )
        beginning_values = prior_relative_wealth.mul(targets, axis="columns")
        beginning_weights = beginning_values.div(
            beginning_values.sum(axis=1),
            axis="index",
        ).where(complete_through_today)
        signed_weights = beginning_weights * (1.0 if leg == "long" else -1.0)
        contributions = signed_weights * returns

        long_form = pd.DataFrame(
            {
                "date": np.repeat(returns.index.to_numpy(), len(symbols)),
                "symbol": np.tile(symbols, len(returns.index)),
                "beginning_abs_weight": beginning_weights.to_numpy().reshape(-1),
                "signed_beginning_weight": signed_weights.to_numpy().reshape(-1),
                "asset_return": returns.to_numpy().reshape(-1),
                "signed_contribution": contributions.to_numpy().reshape(-1),
                "contribution_complete": np.repeat(
                    complete_through_today.to_numpy(),
                    len(symbols),
                ),
            }
        )
        long_form["formation_date"] = formation_date
        long_form["effective_month"] = effective_month
        long_form["leg"] = leg
        long_form["target_weight"] = long_form["symbol"].map(
            active.loc[
                active["effective_month"].eq(effective_month)
                & active["leg"].eq(leg)
            ].set_index("symbol")["target_weight"]
        )
        long_form["loss_contribution"] = (
            -long_form["signed_contribution"]
        ).clip(lower=0.0)
        records.append(long_form)

    if not records:
        return pd.DataFrame(columns=CONSTITUENT_RETURN_COLUMNS)
    result = pd.concat(records, ignore_index=True)
    result = result.loc[:, CONSTITUENT_RETURN_COLUMNS].sort_values(
        ["date", "leg", "symbol"]
    )
    return result.reset_index(drop=True)


def _finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def _exposure_loss_correlation(frame: pd.DataFrame) -> float | None:
    exposure = frame["beginning_abs_weight"].astype("float64")
    loss = frame["loss_contribution"].astype("float64")
    if exposure.nunique() < 2 or loss.nunique() < 2:
        return None
    return _finite_or_none(exposure.corr(loss, method="spearman"))


def build_concentration_history(
    constituent_returns: pd.DataFrame,
    classifications: pd.DataFrame,
) -> pd.DataFrame:
    """Aggregate daily exposure, contribution, and sector concentration."""

    required = set(CONSTITUENT_RETURN_COLUMNS)
    missing = sorted(required - set(constituent_returns.columns))
    if missing:
        raise KeyError(f"constituent returns missing required columns: {missing}")
    if not {"symbol", "sector"}.issubset(classifications.columns):
        raise KeyError("classifications require symbol and sector columns")
    mapping = classifications.loc[:, ["symbol", "sector"]].copy()
    mapping["symbol"] = mapping["symbol"].astype(str)
    if mapping["symbol"].duplicated().any():
        raise ValueError("classifications contain duplicate symbols")

    frame = constituent_returns.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame.merge(mapping, on="symbol", how="left", validate="many_to_one")
    records: list[dict[str, Any]] = []
    for date_value, group in frame.groupby("date", sort=True):
        if not bool(group["contribution_complete"].all()):
            records.append(
                {
                    "date": date_value,
                    "formation_date": group["formation_date"].iloc[0],
                    "effective_month": group["effective_month"].iloc[0],
                    "classification_status": "current_snapshot_proxy",
                    "survivorship_bias": True,
                }
            )
            continue

        sector = sector_concentration(
            group["signed_beginning_weight"],
            group["sector"].tolist(),
        )
        losses = group.loc[group["loss_contribution"].gt(0)].copy()
        top_exposure = set(
            group.nlargest(min(5, len(group)), "beginning_abs_weight")["symbol"]
        )
        top_losses = set(
            losses.nlargest(min(5, len(losses)), "loss_contribution")["symbol"]
        )
        overlap = (
            None
            if not top_losses
            else float(len(top_exposure & top_losses) / len(top_losses))
        )
        records.append(
            {
                "date": date_value,
                "formation_date": group["formation_date"].iloc[0],
                "effective_month": group["effective_month"].iloc[0],
                "effective_bets_abs_exposure": effective_bets(
                    group["signed_beginning_weight"]
                ),
                "top3_abs_exposure_share": top_absolute_share(
                    group["signed_beginning_weight"],
                    top_n=3,
                ),
                "top5_abs_exposure_share": top_absolute_share(
                    group["signed_beginning_weight"],
                    top_n=5,
                ),
                "top3_abs_contribution_share": top_absolute_share(
                    group["signed_contribution"],
                    top_n=3,
                ),
                "top5_abs_contribution_share": top_absolute_share(
                    group["signed_contribution"],
                    top_n=5,
                ),
                "top3_loss_contribution_share": top_absolute_share(
                    losses["loss_contribution"],
                    top_n=3,
                ),
                "top5_loss_contribution_share": top_absolute_share(
                    losses["loss_contribution"],
                    top_n=5,
                ),
                "sector_hhi": sector["sector_hhi"],
                "top_sector_exposure_share": sector[
                    "top_sector_exposure_share"
                ],
                "top_two_sector_exposure_share": sector[
                    "top_two_sector_exposure_share"
                ],
                "missing_sector_exposure_share": sector[
                    "missing_sector_exposure_share"
                ],
                "top5_exposure_loss_overlap_share": overlap,
                "exposure_loss_correlation": _exposure_loss_correlation(group),
                "classification_status": "current_snapshot_proxy",
                "survivorship_bias": True,
            }
        )

    result = pd.DataFrame(records)
    for column in CONCENTRATION_HISTORY_COLUMNS:
        if column not in result:
            result[column] = pd.NA
    return result.loc[:, CONCENTRATION_HISTORY_COLUMNS].sort_values(
        "date"
    ).reset_index(drop=True)


def _holding_duration(
    history: list[set[str]],
    symbol: str,
) -> int:
    duration = 0
    for symbols in reversed(history):
        if symbol not in symbols:
            break
        duration += 1
    return duration


def build_rebalance_diagnostics(holdings: pd.DataFrame) -> pd.DataFrame:
    """Calculate leg overlap, turnover, duration, and rank persistence."""

    required = {"formation_date", "symbol", "leg", "price_momentum_rank"}
    missing = sorted(required - set(holdings.columns))
    if missing:
        raise KeyError(f"holdings missing required columns: {missing}")
    frame = holdings.loc[:, sorted(required)].copy()
    frame["formation_date"] = pd.to_datetime(frame["formation_date"]).dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str)
    frame["price_momentum_rank"] = pd.to_numeric(
        frame["price_momentum_rank"],
        errors="raise",
    )
    if frame.duplicated(["formation_date", "symbol"]).any():
        raise ValueError("holdings contain duplicate formation/symbol rows")

    records: list[dict[str, Any]] = []
    for leg in ("long", "short"):
        leg_frame = frame.loc[frame["leg"].eq(leg)].copy()
        histories: list[set[str]] = []
        previous: pd.DataFrame | None = None
        for formation_date, group in leg_frame.groupby("formation_date", sort=True):
            current_symbols = set(group["symbol"])
            if previous is None:
                overlap_count = 0
                overlap_share = None
                turnover_share = None
                rank_persistence = None
            else:
                overlap_count, overlap_share = holding_overlap(
                    current_symbols,
                    previous["symbol"],
                )
                turnover_share = (
                    None if overlap_share is None else 1.0 - overlap_share
                )
                common = group.merge(
                    previous,
                    on="symbol",
                    suffixes=("_current", "_previous"),
                )
                rank_persistence = (
                    None
                    if len(common) < 2
                    else _finite_or_none(
                        common["price_momentum_rank_current"].corr(
                            common["price_momentum_rank_previous"],
                            method="spearman",
                        )
                    )
                )
            histories.append(current_symbols)
            durations = [
                _holding_duration(histories, symbol)
                for symbol in current_symbols
            ]
            records.append(
                {
                    "formation_date": formation_date,
                    "leg": leg,
                    "holding_count": len(current_symbols),
                    "overlap_count": overlap_count,
                    "overlap_share": overlap_share,
                    "turnover_share": turnover_share,
                    "average_holding_rebalances": float(np.mean(durations)),
                    "rank_persistence": rank_persistence,
                }
            )
            previous = group

    return pd.DataFrame(records, columns=REBALANCE_DIAGNOSTIC_COLUMNS).sort_values(
        ["formation_date", "leg"]
    ).reset_index(drop=True)
