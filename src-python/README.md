# api-server (Python sidecar)

Run standalone (dev) — from the **repository root**:

    uv sync --project src-python
    SIDECAR_TOKEN=devtoken uv run --project src-python python -m app.main

Or from inside `src-python/`:

    uv sync
    SIDECAR_TOKEN=devtoken uv run python -m app.main

The server prints `READY <port>` to stdout. Rust waits for that line.
(PowerShell: `$env:SIDECAR_TOKEN = 'devtoken'; uv run --project src-python python -m app.main`
from the repository root.)

The Rust sidecar spawner passes SIDECAR_TOKEN and --data-dir.
