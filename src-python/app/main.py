"""FastAPI app factory + uvicorn entrypoint with the READY handshake.

Startup contract with Rust (sidecar.rs):
1. Rust spawns this process with SIDECAR_TOKEN=<t> --data-dir <dir> [--port 0].
2. We bind 127.0.0.1:<port> (0 = OS picks), print `READY <port>` with flush=True.
3. Rust polls GET /health, then calls invoke("get_backend") for {port, token}.
4. Shutdown: Rust POSTs /shutdown (auth) then kills as fallback.
   (PyInstaller onefile PID != child PID, so HTTP shutdown is primary.)
"""

from __future__ import annotations

import os
import secrets
import socket
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core import paths
from app.core.config import parse_args


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Single shared httpx client for all harambelogs endpoints."""
    app.state.http_client = httpx.AsyncClient(
        base_url="https://harambelogs.pl",
        timeout=30.0,
        headers={"User-Agent": "TauriSidecar/1.0 (HarambelogsClient)"},
    )
    yield
    await app.state.http_client.aclose()


def create_app(token: str, *, enable_docs: bool = False) -> FastAPI:
    async def verify(request: Request) -> None:
        auth = request.headers.get("authorization", "")
        if not secrets.compare_digest(auth, f"Bearer {token}"):
            raise HTTPException(401, "invalid token")

    app = FastAPI(
        title="api-server",
        lifespan=lifespan,
        openapi_url="/openapi.json" if enable_docs else None,
        docs_url="/docs" if enable_docs else None,
        redoc_url="/redoc" if enable_docs else None,
    )
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
        from app.core.jobs import jobs

        jobs.request_shutdown()
        server = getattr(request.app.state, "server", None)
        if server is not None:
            server.should_exit = True
        return {"status": "shutting down"}

    from app.routers import harambelogs as harambelogs_router
    from app.routers import jobs as jobs_router
    from app.routers import scripts as scripts_router

    app.include_router(scripts_router.router, prefix="/api", dependencies=[Depends(verify)])
    app.include_router(jobs_router.router, prefix="/api", dependencies=[Depends(verify)])
    app.include_router(harambelogs_router.router, prefix="/api/harambelogs", dependencies=[Depends(verify)])

    return app


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    paths.init(args.data_dir)  # everything persistent lives under here

    sockets = None
    if args.port:
        port = args.port
    else:
        # Bind + listen NOW and hand the open socket to uvicorn: closing and
        # rebinding later would let another process steal the port in between
        # (TOCTOU race). NOTE: uvicorn's Config(fd=...) is Unix-only systemd
        # socket activation (AF_UNIX) — broken on Windows. serve(sockets=[...])
        # is the cross-platform equivalent.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        port = sock.getsockname()[1]
        sockets = [sock]

    # Docs/openapi.json only in dev (SIDECAR_DEV=1); production has no
    # unauthenticated schema browser.
    enable_docs = os.environ.get("SIDECAR_DEV") == "1"
    app = create_app(args.token, enable_docs=enable_docs)

    # Rust waits for exactly this line.
    print(f"READY {port}", flush=True)

    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    app.state.server = server
    server.run(sockets=sockets)


if __name__ == "__main__":
    main()
