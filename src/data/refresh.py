"""Download public market data. Does not extend run_mvp past Ken French.

Default live mode re-downloads French, VIX, and S&P/SPY prices, then rebuilds
the 12-1 book and leg-risk panels. If French still ends before ``as_of_date``
after that download, the CLI exits nonzero. It does not invent UMD.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.mvp.daily_brief import last_completed_us_close
from src.utils.io import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    DEFAULT_RAW_DIR,
    read_json,
    write_json,
)

PANEL_FILES = (
    ("french_umd", "french_momentum_factor_daily.parquet"),
    ("french_factors", "french_research_factors_daily.parquet"),
    ("vix_aligned", "vix_aligned.parquet"),
    ("sp500_prices", "sp500_prices.parquet"),
    ("sp500_benchmark", "sp500_benchmark.parquet"),
    ("portfolio_returns", "momentum_portfolio_returns.parquet"),
    ("leg_risk", "leg_risk_history.parquet"),
)


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class DataVintages:
    as_of_date: str
    french: str | None = None
    vix_aligned: str | None = None
    vix_raw: str | None = None
    prices: str | None = None
    spy: str | None = None
    book: str | None = None
    steps: list[StepResult] = field(default_factory=list)
    mode: str = "download"

    @property
    def french_stale(self) -> bool:
        return self.french is None or self.french < self.as_of_date


def parquet_last_date(path: Path) -> str | None:
    if not path.is_file():
        return None
    frame = pd.read_parquet(path, columns=["date"])
    if frame.empty:
        return None
    return pd.to_datetime(frame["date"]).max().normalize().date().isoformat()


def metadata_raw_last(path: Path) -> str | None:
    if not path.is_file():
        return None
    payload = read_json(path)
    if not isinstance(payload, dict):
        return None
    value = payload.get("raw_last_observation")
    return str(value) if value else None


def collect_vintages(
    *,
    as_of_date: str,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    raw_dir: Path = DEFAULT_RAW_DIR,
    steps: list[StepResult] | None = None,
    mode: str = "download",
) -> DataVintages:
    last = {
        key: parquet_last_date(processed_dir / name) for key, name in PANEL_FILES
    }
    vix_raw = None
    sidecar = raw_dir / "VIXCLS.csv.metadata.json"
    if sidecar.is_file():
        try:
            vix_raw = metadata_raw_last(sidecar)
        except (ValueError, KeyError, OSError):
            vix_raw = None
    french = last["french_umd"] or last["french_factors"]
    return DataVintages(
        as_of_date=as_of_date,
        french=french,
        vix_aligned=last["vix_aligned"],
        vix_raw=vix_raw,
        prices=last["sp500_prices"],
        spy=last["sp500_benchmark"],
        book=last["leg_risk"] or last["portfolio_returns"],
        steps=list(steps or []),
        mode=mode,
    )


def format_refresh_report(vintages: DataVintages) -> str:
    """Phone-sized download receipt. Hermes sends this stdout as-is."""

    if vintages.mode == "inspect":
        header = f"Inspect only (no download) as of {vintages.as_of_date}."
    elif vintages.mode == "cached":
        header = f"Rebuilt from cache through {vintages.as_of_date}."
    else:
        header = f"Downloaded through {vintages.as_of_date}."
    french = vintages.french or "missing"
    if vintages.french_stale:
        french_line = (
            f"French: {french} — Ken French has not published through "
            f"{vintages.as_of_date}"
        )
    else:
        french_line = f"French: {french}"
    prices = vintages.prices or "missing"
    spy = vintages.spy or "missing"
    if prices == spy:
        price_line = f"Prices/SPY: {prices}"
    else:
        price_line = f"Prices: {prices}; SPY: {spy}"
    vix = vintages.vix_aligned or "missing"
    if vintages.vix_raw:
        vix_line = f"VIX: {vix} (raw {vintages.vix_raw})"
    else:
        vix_line = f"VIX: {vix}"
    lines = [
        header,
        price_line,
        f"Book: {vintages.book or 'missing'}",
        french_line,
        vix_line,
    ]
    failed = [step.name for step in vintages.steps if not step.ok]
    if failed:
        lines.append("Failed steps: " + ", ".join(failed) + ".")
    if vintages.french_stale:
        lines.append(
            f"No daily brief for {vintages.as_of_date}. Not a quiet day."
        )
    else:
        lines.append(f"Ready for the daily brief on {vintages.as_of_date}.")
    return "\n".join(lines)


def _run_step(
    name: str,
    action: Callable[[], Any],
    *,
    verb: str = "downloading",
) -> StepResult:
    print(f"{verb} {name}...", file=sys.stderr, flush=True)
    try:
        action()
        print(f"{name}: ok", file=sys.stderr, flush=True)
        return StepResult(name=name, ok=True)
    except Exception as exc:
        print(f"{name}: failed: {exc}", file=sys.stderr, flush=True)
        return StepResult(name=name, ok=False, detail=str(exc))


def refresh_data(
    *,
    as_of_date: str | None = None,
    dry_run: bool = False,
    cached: bool = False,
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    raw_dir: Path = DEFAULT_RAW_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> DataVintages:
    """Download panels, then return what landed."""

    resolved = as_of_date or last_completed_us_close()
    as_of = pd.Timestamp(resolved)
    steps: list[StepResult] = []
    if dry_run:
        mode = "inspect"
    elif cached:
        mode = "cached"
    else:
        mode = "download"
    if mode == "download":
        print(
            f"downloading French, VIX, and S&P/SPY through {resolved}...",
            file=sys.stderr,
            flush=True,
        )
    if not dry_run:
        steps.extend(
            _execute_refresh(
                as_of=as_of,
                force=mode == "download",
                processed_dir=processed_dir,
                raw_dir=raw_dir,
                output_dir=output_dir,
            )
        )
    vintages = collect_vintages(
        as_of_date=resolved,
        processed_dir=processed_dir,
        raw_dir=raw_dir,
        steps=steps,
        mode=mode,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir / "data_refresh.json",
        {
            "as_of_date": vintages.as_of_date,
            "french": vintages.french,
            "french_stale": vintages.french_stale,
            "vix_aligned": vintages.vix_aligned,
            "vix_raw": vintages.vix_raw,
            "prices": vintages.prices,
            "spy": vintages.spy,
            "book": vintages.book,
            "steps": [
                {"name": step.name, "ok": step.ok, "detail": step.detail}
                for step in vintages.steps
            ],
        },
    )
    return vintages


def _execute_refresh(
    *,
    as_of: pd.Timestamp,
    force: bool,
    processed_dir: Path,
    raw_dir: Path,
    output_dir: Path,
) -> list[StepResult]:
    from src.data.french import run_french_pipeline
    from src.data.sp500 import (
        build_sp500_benchmark,
        build_sp500_prices,
        build_sp500_universe,
    )
    from src.data.vix import run_vix_pipeline
    from src.portfolio.momentum import run_momentum_portfolio
    from src.risk.leg_decomposition import run_leg_decomposition

    steps: list[StepResult] = []
    steps.append(
        _run_step(
            "french",
            lambda: run_french_pipeline(
                as_of_date=as_of,
                raw_dir=raw_dir,
                processed_dir=processed_dir,
                output_dir=output_dir,
                force=force,
            ),
        )
    )
    steps.append(
        _run_step(
            "vix",
            lambda: run_vix_pipeline(
                as_of_date=as_of,
                raw_dir=raw_dir,
                processed_dir=processed_dir,
                output_dir=output_dir,
                force=force,
            ),
        )
    )
    universe_path = processed_dir / "sp500_universe.parquet"
    if not universe_path.is_file():
        steps.append(
            _run_step(
                "sp500_universe",
                lambda: build_sp500_universe(
                    raw_dir=raw_dir / "sp500",
                    processed_path=universe_path,
                    docs_path=output_dir / "sp500_universe.md",
                    force=force,
                ),
            )
        )
    steps.append(
        _run_step(
            "sp500_prices",
            lambda: build_sp500_prices(
                universe_path=universe_path,
                reusable_prices_path=processed_dir / "universe_prices.parquet",
                processed_path=processed_dir / "sp500_prices.parquet",
                raw_dir=raw_dir / "sp500" / "prices",
                end=as_of + pd.Timedelta(days=1),
                force=force,
            ),
        )
    )
    steps.append(
        _run_step(
            "sp500_benchmark",
            lambda: build_sp500_benchmark(
                raw_dir=raw_dir / "sp500" / "benchmark",
                processed_path=processed_dir / "sp500_benchmark.parquet",
                end=as_of + pd.Timedelta(days=1),
                force=force,
            ),
        )
    )
    steps.append(
        _run_step(
            "portfolio",
            lambda: run_momentum_portfolio(
                processed_dir=processed_dir,
                output_dir=output_dir / "portfolio",
            ),
            verb="rebuilding",
        )
    )
    steps.append(
        _run_step(
            "leg_risk",
            lambda: run_leg_decomposition(
                processed_dir=processed_dir,
                output_dir=output_dir / "risk",
            ),
            verb="rebuilding",
        )
    )
    return steps
