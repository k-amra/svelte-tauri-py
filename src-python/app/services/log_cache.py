"""On-disk cache for chat_stats log fetches (polars parquet).

A full channel fetch is the expensive part of chat_stats. Results are
cached under the Tauri app data dir, so repeated runs — and rebuilt app
versions — reuse them instead of re-downloading.

Validity rules:
- Range fully in the past (to < now - IMMUTABLE_MARGIN_S): chat logs are
  append-only, so the cached frame is immutable -> valid forever.
- Range touching "now" (open end or recent `to`): new messages may have
  arrived -> valid for LIVE_TTL_S only.

Layout:
    <data-dir>/cache/chat_stats/v1/<fingerprint>.parquet   (username/text/ts)
    <data-dir>/cache/chat_stats/v1/<fingerprint>.json      (fetch metadata)

Only the columns compute_stats needs are cached (drops raw/tags/...), which
keeps files small. Bump CACHE_VERSION if the cached schema ever changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from app.core import paths

log = logging.getLogger(__name__)

CACHE_VERSION = "v1"
LIVE_TTL_S = 15 * 60  # ranges that touch "now" expire after this
IMMUTABLE_MARGIN_S = 60 * 60  # ranges ending this far in the past are immutable
MAX_CACHE_BYTES = 500 * 1024 * 1024  # evict oldest entries above this


def _dir() -> Path:
    d = paths.cache_root() / "chat_stats" / CACHE_VERSION
    d.mkdir(parents=True, exist_ok=True)
    return d


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def fingerprint(
    channel_id_type: str, channel: str, from_date: datetime | None, to_date: datetime | None
) -> str:
    """Stable hash of the fetch identity (top_n etc. don't affect the fetch)."""
    canonical = json.dumps(
        {
            "channel_id_type": channel_id_type,
            "channel": channel.strip().lower(),
            "from": _iso(from_date),
            "to": _iso(to_date),
        },
        sort_keys=True,
    )
    return hashlib.sha1(canonical.encode()).hexdigest()[:16]


def is_immutable_range(from_date: datetime | None, to_date: datetime | None) -> bool:
    """True when the whole range is safely in the past (append-only logs)."""
    if to_date is None:
        return False
    to_utc = to_date.astimezone(UTC) if to_date.tzinfo else to_date.replace(tzinfo=UTC)
    return to_utc < datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=IMMUTABLE_MARGIN_S)


def load(fp: str) -> tuple[pl.DataFrame, dict] | None:
    """Return (frame, metadata) on a valid cache hit, else None."""
    base = _dir() / fp
    meta_path = base.with_suffix(".json")
    parquet_path = base.with_suffix(".parquet")
    if not (meta_path.exists() and parquet_path.exists()):
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not meta.get("immutable") and (time.time() - meta.get("fetched_at", 0.0)) >= LIVE_TTL_S:
        return None
    try:
        return pl.read_parquet(parquet_path), meta
    except Exception:  # noqa: BLE001 - corrupted file -> drop and refetch
        log.warning("corrupt cache entry %s — removing", fp)
        _remove(fp)
        return None


def save(fp: str, df: pl.DataFrame, meta: dict) -> None:
    """Atomic write (tmp + rename) so half-written files never load."""
    base = _dir() / fp
    tmp_pq = base.with_suffix(".parquet.tmp")
    tmp_meta = base.with_suffix(".json.tmp")
    try:
        df.write_parquet(tmp_pq)
        tmp_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        os.replace(tmp_pq, base.with_suffix(".parquet"))
        os.replace(tmp_meta, base.with_suffix(".json"))
    except OSError as e:
        log.warning("cache write failed for %s: %s", fp, e)
        for tmp in (tmp_pq, tmp_meta):
            tmp.unlink(missing_ok=True)
        return
    _evict_if_needed()


def _remove(fp: str) -> None:
    for suffix in (".parquet", ".json"):
        (_dir() / fp).with_suffix(suffix).unlink(missing_ok=True)


def _evict_if_needed() -> None:
    d = _dir()
    entries = []
    total = 0
    for pq in sorted(d.glob("*.parquet"), key=lambda p: p.stat().st_mtime):
        meta = pq.with_suffix(".json")
        size = pq.stat().st_size + (meta.stat().st_size if meta.exists() else 0)
        entries.append((pq, meta, size))
        total += size
    for pq, meta, size in entries:
        if total <= MAX_CACHE_BYTES:
            break
        pq.unlink(missing_ok=True)
        meta.unlink(missing_ok=True)
        total -= size
        log.info("cache eviction: removed %s (%d bytes)", pq.name, size)
