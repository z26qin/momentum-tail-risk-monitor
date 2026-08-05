"""Cache-first HTTP retrieval for alternative-data sources.

Every network artifact used by the alternative-data panels is written to disk
with a provenance sidecar. A second run must make **zero** network calls, so
absent resources (for example a FINRA daily file on a non-trading day) are
cached as explicit negative results rather than retried forever.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.utils.io import (
    atomic_write_bytes,
    read_json,
    sha256_file,
    utc_now_iso,
    write_json,
)


USER_AGENT = "momentum-crash/0.1 research pipeline"

# Set to False by the offline verification run so that any attempted network
# call becomes a loud failure instead of a silent refetch.
NETWORK_ENABLED = True


class NetworkDisabledError(RuntimeError):
    """Raised when a cache miss occurs while the network is disabled."""


@dataclass(frozen=True)
class FetchResult:
    """One cached artifact plus how it was obtained."""

    path: Path | None
    metadata: dict[str, Any]
    from_cache: bool

    @property
    def absent(self) -> bool:
        return bool(self.metadata.get("absent", False))

    @property
    def transient_failure(self) -> bool:
        """True when retries were exhausted and nothing was cached."""

        return bool(self.metadata.get("transient_failure", False))

    def read_bytes(self) -> bytes:
        if self.path is None:
            raise FileNotFoundError("Absent resource has no cached payload")
        return self.path.read_bytes()

    def read_text(self) -> str:
        return self.read_bytes().decode("utf-8", errors="replace")

    def read_json(self) -> Any:
        return json.loads(self.read_text())


def _sidecar(path: Path) -> Path:
    return path.with_name(f"{path.name}.metadata.json")


def _validate_cached(path: Path, metadata: dict[str, Any]) -> bool:
    """A cache entry is usable only if the payload still hashes as recorded."""

    if metadata.get("absent"):
        return True
    if not path.is_file():
        return False
    return sha256_file(path) == metadata.get("sha256")


def cached_fetch(
    *,
    cache_path: Path,
    url: str,
    source_key: str,
    method: str = "GET",
    body: bytes | None = None,
    headers: "Mapping[str, str] | Callable[[], Mapping[str, str]] | None" = None,
    absent_statuses: Sequence[int] = (),
    max_retries: int = 5,
    backoff_seconds: float = 10.0,
    min_interval_seconds: float = 1.0,
    timeout_seconds: int = 120,
    force: bool = False,
    tolerate_failure: bool = False,
    validate: "Callable[[bytes], bool] | None" = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> FetchResult:
    """Return a cached artifact, downloading it only on a genuine cache miss.

    ``absent_statuses`` lists HTTP codes that mean "this resource legitimately
    does not exist" (FINRA answers 403 for non-trading days). Those are cached
    as negative results so re-runs stay offline.

    ``tolerate_failure`` turns an exhausted retry budget into a returned
    transient failure instead of an exception. A transient failure is
    deliberately **not** written to the cache, so a later run retries it rather
    than mistaking a rate-limited request for a real absence.
    """

    sidecar_path = _sidecar(cache_path)
    if not force and sidecar_path.is_file():
        metadata = read_json(sidecar_path)
        if _validate_cached(cache_path, metadata):
            return FetchResult(
                path=None if metadata.get("absent") else cache_path,
                metadata=metadata,
                from_cache=True,
            )

    if not NETWORK_ENABLED:
        raise NetworkDisabledError(
            f"Cache miss for {source_key} at {cache_path} while the network is "
            "disabled. The offline determinism check requires a complete cache."
        )

    # Resolved here rather than by the caller so that a header which is
    # expensive, or which requires configuration the caller may not have, is
    # only demanded on the path that actually sends a request. SEC's required
    # contact address works this way: a fully cached run never needs one.
    request_headers = {"User-Agent": USER_AGENT}
    resolved = headers() if callable(headers) else headers
    if resolved:
        request_headers.update(resolved)

    attempts: list[dict[str, Any]] = []
    delay = backoff_seconds
    payload: bytes | None = None
    status: int | None = None
    succeeded = False

    for attempt in range(1, max_retries + 1):
        time.sleep(min_interval_seconds)
        request = urllib.request.Request(
            url, data=body, headers=request_headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read()
                status = response.status
            if validate is not None and not validate(payload):
                # A 200 carrying the wrong content type is a soft failure. GDELT
                # answers throttled requests with a plain-text notice and HTTP
                # 200; caching that would poison the cache permanently.
                attempts.append(
                    {
                        "attempt": attempt,
                        "http_status": status,
                        "rejected_body_prefix": payload[:200].decode(
                            "utf-8", errors="replace"
                        ),
                    }
                )
                payload = None
                if attempt == max_retries and not tolerate_failure:
                    raise RuntimeError(
                        f"{source_key}: response failed validation after "
                        f"{max_retries} attempts"
                    )
                time.sleep(delay)
                delay *= 2
                continue
            attempts.append({"attempt": attempt, "http_status": status})
            succeeded = True
            break
        except urllib.error.HTTPError as error:
            attempts.append({"attempt": attempt, "http_status": error.code})
            if error.code in absent_statuses:
                status = error.code
                payload = None
                succeeded = True
                break
            if attempt == max_retries and not tolerate_failure:
                raise
        except Exception as error:  # noqa: BLE001 - recorded then retried
            attempts.append(
                {"attempt": attempt, "error": f"{type(error).__name__}: {error}"}
            )
            if attempt == max_retries and not tolerate_failure:
                raise
        time.sleep(delay)
        delay *= 2

    if not succeeded:
        # Nothing is written to disk: a rate-limited request is not evidence
        # that the resource is absent, and caching it would poison later runs.
        return FetchResult(
            path=None,
            metadata={
                "source_key": source_key,
                "source_url": url,
                "transient_failure": True,
                "attempts": attempts,
            },
            from_cache=False,
        )

    metadata: dict[str, Any] = {
        "source_key": source_key,
        "source_url": url,
        "http_method": method,
        "retrieval_timestamp_utc": utc_now_iso(),
        "http_status": status,
        "attempts": attempts,
    }
    if extra_metadata:
        metadata.update(dict(extra_metadata))

    if payload is None:
        metadata["absent"] = True
        metadata["absent_reason"] = f"HTTP {status} treated as no-such-resource"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(sidecar_path, metadata)
        return FetchResult(path=None, metadata=metadata, from_cache=False)

    atomic_write_bytes(cache_path, payload)
    metadata["absent"] = False
    metadata["sha256"] = sha256_file(cache_path)
    metadata["bytes"] = cache_path.stat().st_size
    write_json(sidecar_path, metadata)
    return FetchResult(path=cache_path, metadata=metadata, from_cache=False)


def cache_manifest(cache_dir: Path) -> list[dict[str, Any]]:
    """Collect every provenance sidecar under a cache directory."""

    entries = [
        read_json(path)
        for path in sorted(cache_dir.rglob("*.metadata.json"))
        if path.name != "manifest.json"
    ]
    entries.sort(key=lambda item: (item.get("source_key", ""), item.get("source_url", "")))
    return entries
