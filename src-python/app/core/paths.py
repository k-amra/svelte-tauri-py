"""Process-wide paths, initialized once from the --data-dir CLI arg.

Rust passes the Tauri app data dir (sidecar.rs), which lives in the OS
per-app data location and survives app rebuilds/updates as long as the
Tauri identifier stays the same. All persistent sidecar state belongs
under this directory — never next to the (PyInstaller onefile) binary.
"""

from __future__ import annotations

from pathlib import Path

_data_dir: Path | None = None


def init(data_dir: str) -> None:
    """Called once from main() with the CLI --data-dir value."""
    global _data_dir
    _data_dir = Path(data_dir)
    _data_dir.mkdir(parents=True, exist_ok=True)


def data_dir() -> Path:
    """Writable app data dir. Falls back to CWD when init() was skipped (tests)."""
    return _data_dir if _data_dir is not None else Path(".")


def cache_root() -> Path:
    """Shared cache root; created on demand."""
    p = data_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p
