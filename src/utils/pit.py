"""Point-in-time normalisation shared by both alternative-data panels.

The single rule enforced here: the observation being standardised may appear
only in the numerator. Its mean and standard deviation come from the 126
immediately preceding rows and from nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


ROLLING_WINDOW = 126

#: Minimum finite observations required inside the 126-row window for the
#: narrative panel.
#:
#: The original rule demanded all 126. Measured against the live GDELT archive
#: there are **21 gap days across 2017-2026** (3,447 daily buckets returned over
#: 3,468 calendar days). A gap makes one trading row missing, and under the
#: all-126 rule that single row then invalidates the next 126 z-scores — with
#: 21 gaps spread across roughly 2,385 trading rows, the series would be nearly
#: destroyed.
#:
#: This relaxation changes **when a statistic is available, not what its value
#: is**. It is therefore not imputation: no missing observation is filled, and
#: the window remains positionally the 126 rows immediately preceding row t.
#: Requiring 100 of 126 tolerates the observed gap density while still refusing
#: to standardise against a badly incomplete window.
NARRATIVE_MIN_OBSERVATIONS = 100


@dataclass(frozen=True)
class RollingZDiagnostics:
    """Why a z-score is missing, counted rather than silently absorbed."""

    rows: int
    available: int
    missing_current_value: int
    incomplete_window: int
    zero_standard_deviation: int
    window: int = ROLLING_WINDOW
    min_observations: int = ROLLING_WINDOW

    def as_dict(self) -> dict[str, int]:
        return {
            "rows": self.rows,
            "available": self.available,
            "missing_current_value": self.missing_current_value,
            "incomplete_window": self.incomplete_window,
            "zero_standard_deviation": self.zero_standard_deviation,
            "window": self.window,
            "min_observations": self.min_observations,
        }


def rolling_z_pit(
    values: pd.Series,
    window: int = ROLLING_WINDOW,
    min_observations: int | None = None,
) -> tuple[pd.Series, RollingZDiagnostics]:
    """Standardise ``values`` against the ``window`` rows that strictly precede each row.

    The window is **positional**: exactly the ``window`` immediately preceding
    rows of the supplied series, and nothing else. There is never a backward
    search for additional non-missing observations, so a value 200 rows back
    cannot influence row ``t`` no matter how much of the window is missing.

    ``min_observations`` is how many of those ``window`` rows must be finite for
    the statistic to be defined. It defaults to ``window``, the strict rule: one
    missing value makes ``window`` consecutive outputs unavailable. Lowering it
    changes **when a statistic is available, not what its value is** — no
    missing observation is ever filled — which is why relaxing it is not
    imputation.

    A zero standard deviation yields NaN rather than an infinite z-score.
    """

    if window < 2:
        raise ValueError("Rolling z-score window must allow a sample standard deviation")
    min_observations = window if min_observations is None else min_observations
    if not 2 <= min_observations <= window:
        raise ValueError(
            "min_observations must be between 2 and the window length; a sample "
            "standard deviation is undefined below two observations"
        )

    ordered = pd.Series(values, dtype="float64")
    finite = ordered.where(np.isfinite(ordered))

    # shift(1) is the entire point-in-time guarantee: row t never sees itself.
    lagged = finite.shift(1)
    rolling = lagged.rolling(window=window, min_periods=min_observations)
    # The window span stays `window` rows; min_periods only sets how many of
    # them must be non-missing. Rows outside the span are never consulted.
    lagged_mean = rolling.mean()
    lagged_std = rolling.std(ddof=1)

    complete_window = lagged_mean.notna() & lagged_std.notna()
    positive_std = complete_window & (lagged_std > 0)

    z_scores = (finite - lagged_mean) / lagged_std.where(positive_std)
    z_scores = z_scores.where(np.isfinite(z_scores))
    z_scores.index = ordered.index

    diagnostics = RollingZDiagnostics(
        rows=int(len(ordered)),
        available=int(z_scores.notna().sum()),
        missing_current_value=int((finite.isna() & complete_window).sum()),
        incomplete_window=int((~complete_window).sum()),
        zero_standard_deviation=int((complete_window & ~positive_std).sum()),
        window=int(window),
        min_observations=int(min_observations),
    )
    return z_scores, diagnostics
