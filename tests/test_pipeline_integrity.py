"""Integration tests against frozen public-source inputs."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from src.features.labels import run_label_pipeline
from src.features.legs import reconstruct_momentum_legs
from src.features.market_features import run_market_feature_pipeline
from src.utils.io import DEFAULT_PROCESSED_DIR, sha256_file


def test_leg_reconstruction_matches_published_umd() -> None:
    portfolios = pd.read_parquet(
        DEFAULT_PROCESSED_DIR
        / "french_6_size_momentum_portfolios_daily.parquet"
    )
    momentum = pd.read_parquet(
        DEFAULT_PROCESSED_DIR / "french_momentum_factor_daily.parquet"
    )

    reconstructed, stats = reconstruct_momentum_legs(
        portfolios,
        momentum,
    )

    assert len(reconstructed) == len(momentum)
    assert stats["correlation"] >= 0.9999
    assert stats["max_absolute_residual"] <= 0.00011


def test_reproducibility_under_fixed_as_of_date(tmp_path: Path) -> None:
    processed_dir = tmp_path / "data" / "processed"
    output_dir = tmp_path / "outputs"
    processed_dir.mkdir(parents=True)
    required_inputs = (
        "french_momentum_factor_daily.parquet",
        "french_research_factors_daily.parquet",
        "momentum_leg_structure.parquet",
        "vix_aligned.parquet",
    )
    for filename in required_inputs:
        shutil.copyfile(
            DEFAULT_PROCESSED_DIR / filename,
            processed_dir / filename,
        )

    as_of_date = pd.Timestamp("2026-05-29")
    run_label_pipeline(
        as_of_date=as_of_date,
        processed_dir=processed_dir,
        output_dir=output_dir,
    )
    run_market_feature_pipeline(
        as_of_date=as_of_date,
        processed_dir=processed_dir,
        output_dir=output_dir,
    )
    artifacts = (
        processed_dir / "momentum_labels_h5.parquet",
        processed_dir / "momentum_labels_h20.parquet",
        processed_dir / "market_features.parquet",
        output_dir / "task2_label_audit.json",
        output_dir / "task3_feature_audit.json",
    )
    first_hashes = {path.name: sha256_file(path) for path in artifacts}

    run_label_pipeline(
        as_of_date=as_of_date,
        processed_dir=processed_dir,
        output_dir=output_dir,
    )
    run_market_feature_pipeline(
        as_of_date=as_of_date,
        processed_dir=processed_dir,
        output_dir=output_dir,
    )
    second_hashes = {path.name: sha256_file(path) for path in artifacts}

    assert first_hashes == second_hashes
