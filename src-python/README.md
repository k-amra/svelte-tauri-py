# api-server (Python sidecar)
#
# Run standalone (dev):
#   uv sync --project src-python
#   $env:SIDECAR_TOKEN = 'devtoken'; uv run --project src-python python -m app.main
#   curl http://127.0.0.1:<port>/health
#
# The Rust sidecar spawner passes SIDECAR_TOKEN and --data-dir.
# The server prints a single `READY <port>` line to stdout (flush=True);
# Rust waits for that line, then polls GET /health.
