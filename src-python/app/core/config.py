"""CLI args passed by Rust (sidecar.rs) or by a developer in standalone mode."""

import argparse
import os
import secrets


def parse_args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(description="api-server sidecar")
    p.add_argument("--port", type=int, default=0, help="Port to bind (0 = OS picks a free port)")
    p.add_argument(
        "--token",
        default=None,
        help="Development-only token override; production Rust passes SIDECAR_TOKEN",
    )
    p.add_argument(
        "--data-dir",
        default=".",
        help="Writable directory passed by Rust (app_data_dir). Never write next to the binary.",
    )
    args = p.parse_args(argv)
    args.token = args.token or os.environ.get("SIDECAR_TOKEN") or secrets.token_urlsafe(32)
    return args
