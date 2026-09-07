# AGENTS.md

## Project overview

Tauri 2 desktop app. Frontend: Svelte 5 (runes) + shadcn-svelte + Tailwind.
Backend: Python 3.12 FastAPI sidecar, bundled with PyInstaller, spawned by Rust.
Frontend ↔ backend communication is HTTP on 127.0.0.1 with a bearer token.
Rust is ONLY for process lifecycle and native OS access — do not add business logic there.

## Where things live

- `src/lib/api/client.ts` — the only place that calls fetch(). Use it.
- `src/lib/api/backend.svelte.ts` — `$state` store: port, token, status. Call `backend.init()` once.
- `src/lib/api/types.ts` — generated from FastAPI's OpenAPI schema (`bun run gen:types`).
- `src-python/app/scripts/` — all Python logic. One file per capability.
- `src-python/app/routers/` — thin HTTP adapters. No logic here.
- `src-python/app/core/jobs.py` — background job manager for long scripts.
- `src-tauri/src/sidecar.rs` — spawn/health/shutdown. Rarely needs changes.

## How to add a new Python capability

1. Create `src-python/app/scripts/<name>.py` with `Params`, `Result` (Pydantic), `NAME`, `DESCRIPTION`, `run()`.
2. It is auto-registered via `registry.py`. Do not edit routers for this.
3. Regenerate TS types: `bun run gen:types` (pulls `/openapi.json` from a running backend).
4. Add a Svelte component that calls `api.runScript("<name>", params)`.
5. Write a test in `src-python/tests/test_<name>.py`.

## Commands

- `bun run tauri:dev` — Tauri dev + Python via uv (hot reload, `SIDECAR_DEV=1`)
- `bun run tauri:dev:binary` — Tauri dev against the prebuilt PyInstaller binary
- `bun run build:sidecar` — PyInstaller (onedir) → `src-tauri/binaries/`
- `bun run build` — sidecar + frontend (`vite build`); `bun run tauri:build` for the full installer
- `bun run test:python` — `uv run pytest` in `src-python/`
- `bun run test:unit` — Vitest; `bun run test:rust` — `cargo test`
- `bun run check` — svelte-check + tsc; `bun run lint` — prettier + eslint

## Rules / conventions

- Svelte 5 runes only (`$state`, `$derived`, `$props`); no legacy stores or `export let`.
- Every FastAPI route except `/health` requires `Depends(verify_token)`.
- Long-running scripts (>2s) must use the jobs API (`POST /api/jobs`) and report `progress()`.
- Never bind to `0.0.0.0`. Never hardcode the port. Bind `127.0.0.1` only (avoids the Windows Firewall dialog).
- Keep PyInstaller hidden imports in `api_server.spec`, not in code.
- shadcn components: `bunx shadcn-svelte@next add <component>`; don't hand-edit `src/lib/components/ui`.

## Gotchas

- Sidecar binary name must end with the Rust target triple (`rustc --print host-tuple`).
- `externalBin: ["binaries/api-server"]` requires `src-tauri/binaries/api-server-<triple>[.exe]`.
- Capability `name` must match `externalBin` exactly with `"sidecar": true`.
- Killing the PyInstaller PID doesn't kill the child; use `POST /shutdown` first (see `sidecar.rs`).
- After changing Python, rerun `build:sidecar` before testing a release build.
- The Python server must print `READY <port>` with `flush=True`; Rust waits for exactly that line.
- Sidecar is ONEFILE on purpose: Tauri's `externalBin` bundles single files only,
  and the onedir bootloader requires `_internal/` next to the exe while Tauri ships
  `resources/` elsewhere (verified broken: "Failed to load Python DLL"). Do not switch
  back to onedir without solving the `_internal` placement in the installer.

## Packaging & release

- Sidecar is built in `--onefile` mode; single exe → `externalBin`, no `_internal/` dir.
- First launch after install extracts to %TEMP% (2–5s cold start); the UI shows backend status meanwhile.
- Python must never write next to its executable; use `--data-dir` passed by Rust (`app_data_dir()`).
- Sign the sidecar exe BEFORE `tauri build` (`scripts/sign-sidecar.{ps1,sh}`).
- Never enable UPX in the PyInstaller spec (AV false positives).
- Bump version in ONE place: `package.json` → synced to `tauri.conf.json` and `pyproject.toml` by `bun run version`.
- Release = push tag `vX.Y.Z` → CI builds nsis/msi/dmg/deb/rpm/AppImage + `latest.json`.
- Always test the built installer on a clean VM before publishing a release (no Python/Rust on the machine).
- Checklist: app launches, `/health` responds, a script runs, app-data dir is created,
  closing the window leaves NO `api-server` process, uninstall leaves no orphan process.
