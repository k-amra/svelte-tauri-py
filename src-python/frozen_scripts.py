"""PyInstaller bundling hints — single source of truth.

Kept import-free so the PyInstaller spec can `exec()` or read it without
pulling the FastAPI/polars dependency graph into the build environment
before the Analysis() step.

Adding a new script to app/scripts/:
  1. Add its module name below.
  2. That's it — registry.py reads this list, and api_server.spec derives
     its `hiddenimports` entries from it.
"""

# Module names (without the "app.scripts." prefix). Do NOT include
# "registry" or any underscore-prefixed private helper.
FROZEN_SCRIPTS: tuple[str, ...] = (
    "chat_stats",
    "example_task",
)
