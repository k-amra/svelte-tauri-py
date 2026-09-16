# AGENTS.md

Tauri 2 desktop app. Svelte 5 (runes) + shadcn-svelte + Tailwind 4 frontend. Python 3.12
FastAPI sidecar (PyInstaller onefile), spawned by Rust. The sidecar is the only component that
talks to the upstream API (harambelogs.pl); the frontend talks HTTP to the sidecar on
127.0.0.1 with a bearer token.

Rust owns process lifecycle only. No business logic there.

## Working norms

- Read only the files relevant to the task you are doing. Do not load the whole repo map for a small change.
- After any behavior change, run `bun run test` and fix failures caused by your change before finishing.
- Behavior changes must ship with a test that fails without the change.
- If a Pydantic model changes, update the hand-written TS mirror in the same commit.
- When uncertain about a contract, read the source file listed below rather than guessing.

## Where things live

Frontend:

- `src/lib/api/client.ts` — the ONLY place that calls fetch(). Every request goes through it.
- `src/lib/api/backend.svelte.ts` — $state store: port, token, status. Owned by App.svelte.
- `src/lib/views.ts` + `src/lib/components/AppNav.svelte` — view registry. One entry per view.
- `src/lib/api/chatStats.ts` + `harambelogs.ts` — HAND-WRITTEN mirrors of the Python Pydantic
  models. Update them by hand when the backend models change.
- `src/lib/api/export.ts`, `deltas.ts` — client-side helpers, no backend round-trip.

Backend:

- `src-python/app/scripts/` — one file (or package) per capability. All business logic here.
- `src-python/app/routers/` — thin HTTP adapters. No logic.
- `src-python/app/core/jobs.py` — background job manager for scripts over ~2s.
- `src-python/app/services/harambelogs_client.py` — upstream HTTP client.
- `src-python/app/services/log_fetch.py` — pagination + upstream quirk handling.
- `src-python/app/services/log_cache.py` — versioned parquet cache under the app data dir.
- `src-python/frozen_scripts.py` — registration point for new scripts. See below.
- `src-python/api_server.spec` — PyInstaller spec (ONEFILE).

Rust:

- `src-tauri/src/sidecar.rs` — spawn, READY handshake, health, shutdown, diagnostics.
- `src-tauri/src/commands/default.rs` — read/write for greet.txt/name.txt, path-allowlisted.

## Adding a Python capability

Follow these steps in order. Step 2 is the one most often missed and is the #1 way to ship a
broken release.

1. Create `src-python/app/scripts/<name>.py` (or `<name>/__init__.py`) with `Params`, `Result`
   (Pydantic), `NAME`, `DESCRIPTION`, `run(params, progress)`. Copy `example_task.py`.
2. Add the module name to `FROZEN_SCRIPTS` in `src-python/frozen_scripts.py`.
   Reason: in dev, `registry.py` scans the filesystem and finds the new file anyway; in the
   packaged app it does not, because PyInstaller puts modules in a PYZ archive where filesystem
   discovery is unreliable. A missing entry works in `tauri:dev` and silently disappears from
   the built app.
3. Add a test in `src-python/tests/test_<name>.py`. The PyInstaller spec derives hidden imports
   from `FROZEN_SCRIPTS`, so no spec edit is needed.
4. Frontend: new component calling `api.runScript("<name>", params)`, or `api.createJob(...)`
   for anything over 2s.
5. If the result has a rich shape, add a hand-written TS interface next to `chatStats.ts`.

The router, registry, and PyInstaller hidden imports all derive from `FROZEN_SCRIPTS`. Do not
edit `routers/` for this.

## Auth

- Rust generates a UUID per launch, passes it to Python via `SIDECAR_TOKEN` env, and exposes it
  to the frontend via `invoke("get_backend")`.
- Python checks `Authorization: Bearer <token>` with `compare_digest`. Every route except
  `/health` requires it.
- The frontend reads the token from `backend.svelte.ts`. `client.ts` attaches it. No other
  module touches it.
- `/openapi.json` is enabled only when `SIDECAR_DEV=1`.

## Commands

- `bun run tauri:dev` — dev with uv + hot reload (`SIDECAR_DEV=1`)
- `bun run tauri:dev:binary` — dev against the prebuilt sidecar
- `bun run build:sidecar` — PyInstaller onefile → `src-tauri/binaries/api-server-<triple>(.exe)`
- `bun run test` — check + lint + vitest + cargo test + pytest
- `bun run build:app` — full installer

## Gotchas

PyInstaller / sidecar:

- ONEFILE is deliberate. Tauri's `externalBin` bundles single files only; onedir's `_internal/`
  placement breaks in the installer. Do not switch back.
- Binary name must end with the Rust target triple: `api-server-<triple>[.exe]`.
- The capability `name` in `src-tauri/capabilities/default.json` must match `externalBin` exactly.
- `console=True` in the spec is load-bearing. Rust reads `READY <port>` from stdout; anything
  written to stdout before that line races the handshake.
- Do not enable UPX. It causes antivirus false positives.

Shutdown:

- `POST /shutdown` is the primary mechanism. Rust kills the process tree as a fallback
  (`taskkill /T` on Windows; the onefile bootloader's child survives a bare `kill()`).

Cache:

- `log_cache.py` has `CACHE_VERSION = "v4"`. Bump it whenever the cached parquet schema changes.
- Cache lives at `<data-dir>/cache/chat_stats/v4/<channel_id_type>_<channel>/YYYY_MM.parquet`.

Upstream (harambelogs.pl):

- Deep offsets are refused around ~30k even when messages exist beyond. `log_fetch.py` detects
  this via `/stats` and time-splits the span recursively (max depth 8). Do not remove the split.
- Zero-byte 2xx bodies are transient, not "no data". They are retryable.
- The upstream is hardcoded in `harambelogs_client.py` (`BASE_URL`) and `main.py`. Not configurable.

Frontend types:

- `src/lib/api/types.ts` is a placeholder. The types the app actually uses are in `chatStats.ts`
  and `harambelogs.ts`, maintained by hand.

CI / release:

- CI: `.github/workflows/test-build.yml`. Clippy is warn-only on purpose: the stable toolchain
  floats, so new lints must not break unrelated PRs.
- Release: push tag `vX.Y.Z`. `validate-release` checks 5 version files match the tag.
  `sync-versions.mjs` updates them (`bun run version`).
- Signing: the sidecar is signed BEFORE `tauri build`. `SIDECAR_PREBUILT=1` makes the
  beforeBuildCommand skip the rebuild and preserve the signature.

Version bumping:

- `bun run version` syncs `package.json` → `tauri.conf.json`, `Cargo.toml` [package],
  `pyproject.toml`. `Cargo.lock` and `bun.lock` update on the next `cargo check` / `bun install`.
- `chat_stats` carries its own description version ("v4.5"). Bump the `DESCRIPTION` string when
  its behavior changes.

## Definition of done

- Behavior change ships with a test that fails without it. `example_task.py` is the shape to copy.
- `bun run test` passes.
- If the sidecar contract changed (spawn, READY, shutdown, packaging), run `bun run build:sidecar`
  and launch against the rebuilt binary.
- If a Pydantic model changed, the hand-written TS mirror is updated in the same commit.

## Safety

- Do not commit secrets. The token is generated at runtime and never stored.
- Do not run `rm -rf`, `git reset --hard`, `git push --force`, or `DROP TABLE` without explicit
  confirmation from the user.
- Do not use `--no-verify`. Fix the failing hook instead.
- Do not commit binaries or `dist/`.
- Do not push directly to `main`. Use a feature branch.
