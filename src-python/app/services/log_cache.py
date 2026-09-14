"""On-disk cache for chat_stats log fetches (polars parquet), chunked by month.

A full channel fetch is the expensive part of chat_stats. Results are
cached under the Tauri app data dir, so repeated runs — and rebuilt app
versions — reuse them instead of re-downloading.

Chunking: one entry per channel per calendar month (``YYYY_MM``) instead
of one entry per exact date range. Shifting the requested range by a day
no longer misses the cache: the overlapping months load straight from
disk and only genuinely missing spans are downloaded.

Each chunk tracks its *coverage* as a list of fetched intervals
(``coverage``; legacy chunks carry a single ``covered_from``/``covered_to``
pair, which still reads). A chunk is ``complete`` only when a single
interval spans the whole month and no contributing fetch truncated. Validity rules:

- Month fully in the past (next month starts before now - margin): chat
  logs are append-only, so the chunk is immutable -> valid forever.
  Immutability is re-evaluated at load time, so a chunk saved as live
  promotes itself once its month ages into the past.
- Current ("live") month: new messages may arrive -> valid for
  LIVE_TTL_S only. Expired live chunks are returned with
  ``allow_stale=True`` so the caller can top up just the tail instead of
  re-downloading the month.

Layout:
    <data-dir>/cache/chat_stats/v4/<id_type>_<channel>/2026_09.parquet
    <data-dir>/cache/chat_stats/v4/<id_type>_<channel>/2026_09.json

Only the columns compute_stats needs are cached (drops raw/tags/...), which
keeps files small. Bump CACHE_VERSION if the cached schema ever changes
(the loader purges older version dirs).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from app.core import paths

log = logging.getLogger(__name__)

CACHE_VERSION = "v4"
LIVE_TTL_S = 15 * 60  # current ("live") months expire after this
IMMUTABLE_MARGIN_S = 60 * 60  # months ending this far in the past are immutable
MAX_CACHE_BYTES = 500 * 1024 * 1024  # evict oldest entries above this

# Eviction scans the whole cache dir (rglob + stat per file). Running it on
# every save makes fetch latency depend on total cache size. Throttle to at
# most once per hour; the cache grows by at most one month per fetch, so a
# single hourly sweep comfortably keeps it under MAX_CACHE_BYTES.
# (The timestamp starts at 0, so the first save of each process always
# sweeps — no separate startup hook needed.)
EVICT_MIN_INTERVAL_S = 60 * 60
_last_evict_ts: float = 0.0


_cleaned_versions: bool = False


def _dir() -> Path:
    global _cleaned_versions
    root = paths.cache_root() / "chat_stats"
    root.mkdir(parents=True, exist_ok=True)
    d = root / CACHE_VERSION
    d.mkdir(parents=True, exist_ok=True)
    # Drop caches written by older app versions (different frame schema):
    # without this each version could hoard up to MAX_CACHE_BYTES forever.
    # One sweep per process is enough; this runs on every load/save.
    if not _cleaned_versions:
        _cleaned_versions = True
        for child in root.iterdir():
            if child.is_dir() and child.name != CACHE_VERSION:
                shutil.rmtree(child, ignore_errors=True)
                log.info("cache cleanup: removed outdated version dir %s", child.name)
    return d


def _channel_dir(channel_id_type: str, channel: str) -> Path:
    # Channel is part of the path now (not just the hash input): sanitize
    # defensively even though Twitch logins are already [A-Za-z0-9_].
    safe_channel = "".join(c if c.isalnum() else "_" for c in channel.strip().lower())
    d = _dir() / f"{channel_id_type}_{safe_channel}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def month_key(year: int, month: int) -> str:
    return f"{year:04d}_{month:02d}"


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Half-open [start, end) UTC bounds of a calendar month."""
    start = datetime(year, month, 1, tzinfo=UTC)
    end = datetime(year + 1, 1, 1, tzinfo=UTC) if month == 12 else datetime(year, month + 1, 1, tzinfo=UTC)
    return start, end


def is_month_immutable(year: int, month: int) -> bool:
    """True once the whole month is safely in the past (append-only logs)."""
    _, end = month_bounds(year, month)
    return end < datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=IMMUTABLE_MARGIN_S)


def get_month_paths(channel_id_type: str, channel: str, year: int, month: int) -> tuple[Path, Path]:
    base = _channel_dir(channel_id_type, channel) / month_key(year, month)
    return base.with_suffix(".parquet"), base.with_suffix(".json")


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def coverage_intervals(meta: dict) -> list[tuple[datetime, datetime]]:
    """Return coverage as a sorted list of non-overlapping UTC intervals.

    Reads the `coverage` field (list of [from_iso, to_iso] pairs). Falls
    back to the legacy single [covered_from, covered_to] pair so chunks
    written before this schema change stay readable.
    """
    raw = meta.get("coverage")
    intervals: list[tuple[datetime, datetime]] = []
    if isinstance(raw, list):
        for pair in raw:
            try:
                s = _parse_iso(pair[0])
                e = _parse_iso(pair[1])
            except (IndexError, TypeError):
                continue
            if s is not None and e is not None and s < e:
                intervals.append((s, e))
    if intervals:
        return sorted(intervals, key=lambda x: x[0])

    # Legacy single-interval fallback
    s = _parse_iso(meta.get("covered_from"))
    e = _parse_iso(meta.get("covered_to"))
    if s is not None and e is not None and s < e:
        return [(s, e)]
    return []


def merge_coverage(
    intervals: list[tuple[datetime, datetime]],
    new: tuple[datetime, datetime],
) -> list[tuple[datetime, datetime]]:
    """Insert `new` into `intervals`, merging overlaps and touching intervals."""
    if new[0] >= new[1]:
        return list(intervals)
    combined = sorted(list(intervals) + [new], key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = [combined[0]]
    for s, e in combined[1:]:
        last_s, last_e = merged[-1]
        if s <= last_e:
            merged[-1] = (last_s, max(last_e, e))
        else:
            merged.append((s, e))
    return merged


def covers(
    intervals: list[tuple[datetime, datetime]],
    need_from: datetime,
    need_to: datetime,
) -> bool:
    """True if any single interval fully contains [need_from, need_to)."""
    return any(s <= need_from and e >= need_to for s, e in intervals)


def load_month(
    channel_id_type: str, channel: str, year: int, month: int, *, allow_stale: bool = False
) -> tuple[pl.DataFrame, dict] | None:
    """Return (frame, metadata) for a month chunk on a valid hit, else None.

    With ``allow_stale=True``, expired live months are returned too, so the
    caller can top up the tail incrementally instead of re-downloading.
    Missing/corrupt entries still return None.
    """
    parquet_path, meta_path = get_month_paths(channel_id_type, channel, year, month)
    if not (meta_path.exists() and parquet_path.exists()):
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    meta["immutable"] = is_month_immutable(year, month)
    if not allow_stale and not meta["immutable"] and (time.time() - meta.get("fetched_at", 0.0)) >= LIVE_TTL_S:
        return None
    try:
        return pl.read_parquet(parquet_path), meta
    except Exception:  # noqa: BLE001 - corrupted file -> drop and refetch
        log.warning("corrupt cache entry %s — removing", parquet_path)
        parquet_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        return None


def save_month(
    channel_id_type: str, channel: str, year: int, month: int, df: pl.DataFrame, meta: dict
) -> None:
    """Atomic write (tmp + rename) so half-written files never load."""
    parquet_path, meta_path = get_month_paths(channel_id_type, channel, year, month)
    # Unique suffix per writer: two concurrent saves to the same month would
    # otherwise share one tmp path and (on Windows) raise WinError 32, or
    # (on POSIX) interleave writes into a corrupt Parquet footer.
    tmp_id = uuid.uuid4().hex[:8]
    tmp_pq = parquet_path.with_suffix(f".{tmp_id}.parquet.tmp")
    tmp_meta = meta_path.with_suffix(f".{tmp_id}.json.tmp")
    try:
        df.write_parquet(tmp_pq)
        tmp_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        os.replace(tmp_pq, parquet_path)
        os.replace(tmp_meta, meta_path)
    except OSError as e:
        log.warning("cache write failed for %s: %s", parquet_path, e)
        for tmp in (tmp_pq, tmp_meta):
            tmp.unlink(missing_ok=True)
        return

    global _last_evict_ts
    now = time.monotonic()
    if now - _last_evict_ts >= EVICT_MIN_INTERVAL_S:
        _last_evict_ts = now
        _evict_if_needed()


def _evict_if_needed() -> None:
    d = _dir()
    entries = []
    total = 0
    for pq in sorted(d.rglob("*.parquet"), key=lambda p: p.stat().st_mtime):
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
