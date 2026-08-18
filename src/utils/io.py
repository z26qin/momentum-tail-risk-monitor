"""Small, auditable I/O helpers for public-source data."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw"
DEFAULT_PROCESSED_DIR = REPO_ROOT / "data" / "processed"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs"


def load_dotenv_if_present(env_path: Path | None = None) -> None:
    """Load simple KEY=VALUE pairs from a local ``.env`` without new deps."""

    path = env_path if env_path is not None else REPO_ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def utc_now_iso() -> str:
    """Return an auditable UTC retrieval timestamp."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    """Hash a file without loading the whole object into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Write bytes atomically within the destination directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(payload)
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def write_json(path: Path, payload: Any) -> None:
    """Write deterministic, human-readable JSON."""

    atomic_write_bytes(
        path,
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def read_json(path: Path) -> Any:
    """Read JSON from disk."""

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _metadata_path(raw_path: Path) -> Path:
    return raw_path.with_name(f"{raw_path.name}.metadata.json")


def cache_public_source(
    *,
    source_key: str,
    source_url: str,
    raw_path: Path,
    local_source: Path | None = None,
    force: bool = False,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    """Cache an immutable raw object and preserve retrieval provenance.

    A local source is an explicit offline import of bytes previously obtained
    from ``source_url``. Its original filesystem modification time is recorded
    rather than presented as a vendor retrieval timestamp.
    """

    metadata_path = _metadata_path(raw_path)
    if raw_path.exists() and metadata_path.exists() and not force:
        metadata = read_json(metadata_path)
        actual_hash = sha256_file(raw_path)
        if metadata["sha256"] != actual_hash:
            raise ValueError(
                f"Cached raw file hash changed for {raw_path}; "
                "use a new cache or explicitly force replacement."
            )
        return metadata

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    retrieval_timestamp = utc_now_iso()

    if local_source is not None:
        if not local_source.is_file():
            raise FileNotFoundError(f"Offline source does not exist: {local_source}")
        temporary_path = raw_path.with_name(f".{raw_path.name}.importing")
        shutil.copyfile(local_source, temporary_path)
        temporary_path.replace(raw_path)
        retrieval_method = "offline_import"
        source_file_mtime = datetime.fromtimestamp(
            local_source.stat().st_mtime, tz=timezone.utc
        ).isoformat(timespec="seconds")
    else:
        request = urllib.request.Request(
            source_url,
            headers={"User-Agent": "momentum-crash/0.1 research pipeline"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read()
        except Exception as exc:
            raise RuntimeError(
                f"Could not retrieve {source_url}. Provide the official raw file "
                "with --offline-dir for a network-restricted rerun."
            ) from exc
        atomic_write_bytes(raw_path, payload)
        retrieval_method = "direct_download"
        source_file_mtime = None

    metadata: dict[str, Any] = {
        "source_key": source_key,
        "source_url": source_url,
        "cached_path": str(raw_path.relative_to(REPO_ROOT)),
        "retrieval_timestamp_utc": retrieval_timestamp,
        "retrieval_method": retrieval_method,
        "sha256": sha256_file(raw_path),
        "bytes": raw_path.stat().st_size,
    }
    if local_source is not None:
        metadata["offline_import_path"] = str(local_source.resolve())
        metadata["offline_source_file_mtime_utc"] = source_file_mtime

    write_json(metadata_path, metadata)
    return metadata


def update_raw_metadata(raw_path: Path, **fields: Any) -> dict[str, Any]:
    """Add parsed-observation audit fields to a raw object's sidecar."""

    metadata_path = _metadata_path(raw_path)
    metadata = read_json(metadata_path)
    metadata.update(fields)
    write_json(metadata_path, metadata)
    return metadata


def rebuild_raw_manifest(raw_dir: Path) -> list[dict[str, Any]]:
    """Build one sorted manifest from all per-file sidecars."""

    entries = [
        read_json(path)
        for path in sorted(raw_dir.glob("*.metadata.json"))
        if path.name != "manifest.json"
    ]
    entries.sort(key=lambda item: item["source_key"])
    write_json(raw_dir / "manifest.json", entries)
    return entries


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Write a stable parquet artifact with no implicit index."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    frame.to_parquet(temporary_path, index=False, engine="pyarrow")
    temporary_path.replace(path)


def parse_as_of_date(value: str) -> pd.Timestamp:
    """Parse a required ISO date and reject timestamps or ambiguous formats."""

    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("AS_OF_DATE must be exactly YYYY-MM-DD") from exc
    return pd.Timestamp(parsed)


def iso_date(value: pd.Timestamp) -> str:
    """Render a pandas timestamp as an ISO calendar date."""

    return value.date().isoformat()

