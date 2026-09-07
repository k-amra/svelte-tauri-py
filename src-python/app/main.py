"""FastAPI app factory + uvicorn entrypoint with the READY handshake.

Startup contract with Rust (sidecar.rs):
1. Rust spawns this process with SIDECAR_TOKEN=<t> --data-dir <dir> [--port 0].
2. We bind 127.0.0.1:<port> (0 = OS picks), print `READY <port>` with flush=True.
3. Rust polls GET /health, then calls invoke("get_backend") for {port, token}.
4. Shutdown: Rust POSTs /shutdown (auth) then kills as fallback.
   (PyInstaller onefile PID != child PID, so HTTP shutdown is primary.)
"""

from __future__ import annotations

import argparse
import socket
import sys

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import parse_args


def get_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def create_app(token: str) -> FastAPI:
    async def verify(request: Request) -> None:
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {token}":
            raise HTTPException(401, "invalid token")

    app = FastAPI(title="api-server")
    app.state.token = token
    app.state.verify_token = verify

    app.add_middleware(
        CORSMiddleware,
        # Tauri 2 uses http://tauri.localhost for the Windows production WebView.
        # Keep the dev origins and the legacy tauri:// origin for other platforms.
        allow_origins=[
            "http://tauri.localhost",
            "tauri://localhost",
            "http://localhost:1420",
            "http://127.0.0.1:1420",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/shutdown", dependencies=[Depends(verify)])
    async def shutdown(request: Request):
        server = getattr(request.app.state, "server", None)
        if server is not None:
            server.should_exit = True
        return {"status": "shutting down"}

    from app.routers import jobs as jobs_router
    from app.routers import scripts as scripts_router
    from app.routers import harambelogs as harambelogs_router

    app.include_router(scripts_router.router, prefix="/api", dependencies=[Depends(verify)])
    app.include_router(jobs_router.router, prefix="/api", dependencies=[Depends(verify)])
    app.include_router(harambelogs_router.router, prefix="/api/harambelogs", dependencies=[Depends(verify)])

    return app


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    port = args.port if args.port else get_free_port()

    app = create_app(args.token)

    # Rust waits for exactly this line.
    print(f"READY {port}", flush=True)

    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    app.state.server = server
    server.run()


if __name__ == "__main__":
    main()
