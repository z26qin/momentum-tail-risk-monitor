"""Read the frozen B2 model only as an optional shadow benchmark."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.mvp.contracts import PrimaryRiskAssessment, ShadowBenchmark
from src.utils.io import DEFAULT_OUTPUT_DIR


def build_b2_shadow(
    *,
    primary: PrimaryRiskAssessment,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> ShadowBenchmark:
    """Return a research-only B2 comparison without changing primary risk."""

    path = output_dir / "baseline_predictions.parquet"
    if not path.is_file():
        return ShadowBenchmark(
            name="B2_logistic",
            status="unavailable",
            shadow_probability=None,
            shadow_percentile=None,
            agrees_with_primary=None,
            detail="Frozen B2 predictions are unavailable; primary DM state is unaffected.",
        )

    as_of_date = pd.Timestamp(primary.as_of_date)
    predictions = pd.read_parquet(
        path,
        columns=[
            "scope",
            "horizon_days",
            "baseline",
            "split_id",
            "date",
            "predicted_probability",
        ],
        filters=[
            ("horizon_days", "=", primary.horizon_days),
            ("baseline", "=", "B2"),
        ],
    )
    selected = predictions.loc[predictions["date"].eq(as_of_date)]
    if len(selected) != 1:
        return ShadowBenchmark(
            name="B2_logistic",
            status="unavailable",
            shadow_probability=None,
            shadow_percentile=None,
            agrees_with_primary=None,
            detail=(
                "No unique frozen OOS B2 prediction exists for this date; "
                "primary DM state is unaffected."
            ),
        )

    row = selected.iloc[0]
    comparable = predictions.loc[
        predictions["scope"].eq(row["scope"])
        & predictions["split_id"].eq(row["split_id"])
        & predictions["date"].le(as_of_date)
    ]
    probability = float(row["predicted_probability"])
    percentile = float(
        comparable["predicted_probability"].le(probability).mean()
    )
    shadow_high = percentile >= 0.75
    return ShadowBenchmark(
        name="B2_logistic",
        status="available",
        shadow_probability=probability,
        shadow_percentile=percentile,
        agrees_with_primary=shadow_high == primary.elevated,
        detail=(
            "Research-only frozen OOS B2 probability. Agreement compares the "
            "primary elevated flag with whether B2 is at or above its 75th "
            "PIT percentile inside the same saved split; this is not an alert "
            "threshold and does not modify primary risk."
        ),
    )
