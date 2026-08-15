"""Lightweight tests for the data-refresh CLI (no network)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.refresh import (
    DataVintages,
    collect_vintages,
    format_refresh_report,
    parquet_last_date,
    refresh_data,
)


def test_parquet_last_date_and_stale_report(tmp_path: Path) -> None:
    frame = pd.DataFrame({"date": pd.to_datetime(["2026-06-30"])})
    path = tmp_path / "french_momentum_factor_daily.parquet"
    frame.to_parquet(path)
    assert parquet_last_date(path) == "2026-06-30"
    assert parquet_last_date(tmp_path / "missing.parquet") is None
    vintages = DataVintages(as_of_date="2026-07-30", french="2026-06-30")
    assert vintages.french_stale is True
    text = format_refresh_report(vintages)
    assert "Refresh as of 2026-07-30" in text
    assert "2026-06-30 — stale" in text
    assert "Not a complete run_mvp date" in text
    assert "Do not invent UMD" in text


def test_fresh_french_is_ready() -> None:
    vintages = DataVintages(as_of_date="2026-06-30", french="2026-06-30")
    assert vintages.french_stale is False
    assert "Ready for run_mvp" in format_refresh_report(vintages)


def test_dry_run_inspects_without_download(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    processed.mkdir()
    pd.DataFrame({"date": pd.to_datetime(["2026-06-30"])}).to_parquet(
        processed / "french_momentum_factor_daily.parquet"
    )
    pd.DataFrame({"date": pd.to_datetime(["2026-06-30"])}).to_parquet(
        processed / "leg_risk_history.parquet"
    )
    vintages = refresh_data(
        as_of_date="2026-07-30",
        dry_run=True,
        processed_dir=processed,
        raw_dir=tmp_path / "raw",
        output_dir=tmp_path / "outputs",
    )
    assert vintages.french == "2026-06-30"
    assert vintages.book == "2026-06-30"
    assert vintages.french_stale is True
    assert vintages.steps == []
    assert (tmp_path / "outputs" / "data_refresh.json").is_file()


def test_collect_vintages_reads_vix_sidecar(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    processed.mkdir()
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "VIXCLS.csv.metadata.json").write_text(
        '{"raw_last_observation": "2026-08-03"}',
        encoding="utf-8",
    )
    vintages = collect_vintages(
        as_of_date="2026-07-30",
        processed_dir=processed,
        raw_dir=raw,
    )
    assert vintages.vix_raw == "2026-08-03"
    assert "raw 2026-08-03" in format_refresh_report(vintages)


def test_refresh_cli_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts" / "refresh_data.py").is_file()
    assert (root / "src" / "data" / "refresh.py").is_file()
