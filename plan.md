I'll look at the template and current Tauri 2 sidecar patterns to give you an accurate proposal.Here's a proposal for the architecture, based on that template plus the established Tauri 2 → Python sidecar pattern.

## 1. What you're combining

The base template is a clean desktop application template that combines Tauri 2 with Svelte 5 + Shadcn-svelte, including automated CI/CD pipelines for Windows, Linux, and Mac builds. To that you add a Python sidecar: you may need to embed external binaries to add additional functionality to your application or prevent users from installing additional dependencies (e.g., Node.js or Python). We call this binary a sidecar. Binaries are executables written in any programming language. Common use cases are Python CLI applications or API servers bundled using pyinstaller.

The key design point: the Python backend and Rust frontend are separate processes communicating over HTTP. This separation makes development easier and makes the architecture more resilient—one component crashing doesn't take down the other.

## 2. Proposed repository layout

```
my-app/
├── AGENTS.md                      # instructions for AI coding agents (see §6)
├── package.json                   # bun scripts: dev, build, build:sidecar
├── src/                           # Svelte 5 + shadcn-svelte (unchanged from template)
│   ├── lib/
│   │   ├── api/
│   │   │   ├── client.ts          # typed fetch wrapper → FastAPI
│   │   │   ├── types.ts           # generated from FastAPI's OpenAPI schema
│   │   │   └── backend.svelte.ts  # $state store: port, token, status
│   │   └── components/ui/         # shadcn
│   └── routes/
├── src-tauri/
│   ├── tauri.conf.json            # externalBin: ["binaries/api-server"]
│   ├── capabilities/default.json  # shell:allow-execute for the sidecar only
│   ├── binaries/                  # PyInstaller output lands here (gitignored)
│   │   └── api-server-x86_64-pc-windows-msvc.exe  etc.
│   └── src/
│       ├── lib.rs
│       └── sidecar.rs             # spawn, health-wait, kill-on-exit
├── src-python/
│   ├── pyproject.toml             # uv/poetry; fastapi, uvicorn, pyinstaller
│   ├── api_server.spec            # PyInstaller spec (not --onefile flags, see §5)
│   ├── app/
│   │   ├── main.py                # FastAPI app factory + uvicorn entrypoint
│   │   ├── routers/               # one router per feature
│   │   ├── scripts/               # ← your actual Python "scripts"
│   │   │   ├── __init__.py
│   │   │   ├── registry.py        # discovers scripts, exposes metadata
│   │   │   ├── example_task.py
│   │   │   └── ...
│   │   └── core/
│   │       ├── config.py          # port, token, data dir (from env/args)
│   │       └── jobs.py            # background job manager for long scripts
│   └── tests/
└── .github/workflows/             # template's release.yml + a "build sidecar" step
```

## 3. Process & communication flow

```
┌──────────────┐  invoke("get_backend")   ┌──────────────┐  spawn + stdout  ┌──────────────┐
│  Svelte UI   │ ───────────────────────► │  Rust (Tauri)│ ───────────────► │ FastAPI      │
│  (webview)   │ ◄─── { port, token } ─── │  sidecar.rs  │ ◄── "READY:port" │ (PyInstaller)│
│              │                          └──────────────┘                  │              │
│              │  fetch http://127.0.0.1:{port}/api/...  Authorization: Bearer {token}     │
│              │ ◄──────────────────────────────────────────────────────────►│ scripts/*.py │
└──────────────┘                                                            └──────────────┘
```

**Startup sequence (Rust owns the lifecycle):**
1. Tauri `setup()` generates a random token and picks a free port (bind to `127.0.0.1:0`, read the port, release it).
2. Spawn sidecar via `tauri-plugin-shell` with args `--port 0 --token <t>` (or pass through env). Python binds to the port and prints a single line `READY <port>` to stdout.
3. Rust waits for that line (with timeout), then polls `GET /health` once to confirm.
4. Rust stores `{port, token}` in managed state; frontend calls `invoke("get_backend")` and builds its API client.
5. On window close / `RunEvent::Exit`, Rust sends `POST /shutdown` (graceful) and then kills the process. Note the important gotcha: we cannot use process.kill() for one-file Python executables since Tauri only knows the pid of the PyInstaller bootloader process and not its' child process (which is actually the sidecar). So the HTTP `/shutdown` endpoint (or a stdin `shutdown` line) is the primary mechanism, kill is the fallback.

**Why the frontend talks HTTP directly instead of via Rust commands:** it keeps Rust to ~100 lines of lifecycle code, and you get FastAPI's OpenAPI schema for free to generate TypeScript types. If you are not comfortable coding in Rust, this setup allows you to focus primarily on the frontend and the backend API interaction via standard HTTP requests.

**Security minimums:** bind to `127.0.0.1` only, require the bearer token on every route, restrict CORS to `tauri://localhost` and `http://localhost:1420` (dev), and in `capabilities/default.json` allow `shell:allow-execute` only for the named sidecar—not arbitrary commands.

## 4. How Python scripts plug in

Treat `scripts/` as the "business logic" layer and FastAPI as a thin adapter. Each script exposes a uniform interface:

```python
# src-python/app/scripts/example_task.py
from pydantic import BaseModel

class Params(BaseModel):
    input_path: str
    threshold: float = 0.5

class Result(BaseModel):
    count: int
    output_path: str

NAME = "example_task"
DESCRIPTION = "Counts things above a threshold."

def run(params: Params, progress=lambda pct, msg="": None) -> Result:
    ...
```

`registry.py` imports everything in `scripts/`, and a generic router exposes:

| Endpoint | Purpose |
|---|---|
| `GET /health` | readiness (no auth, used by Rust) |
| `GET /api/scripts` | list scripts + their JSON Schema (from Pydantic) → UI can auto-render forms |
| `POST /api/scripts/{name}/run` | sync run for fast scripts |
| `POST /api/jobs` `{script, params}` | start long-running script → returns `job_id` |
| `GET /api/jobs/{id}` | status/progress/result |
| `GET /api/jobs/{id}/events` | SSE stream for live progress/log lines |
| `POST /shutdown` | graceful stop |

Adding a new capability = drop a file in `scripts/`, no Rust change, no manual route wiring.

## 5. Build pipeline

- `bun run build:sidecar` → runs `pyinstaller api_server.spec` in `src-python/`, then renames/copies output to `src-tauri/binaries/api-server-<target-triple>`. Wrong target triple naming means Tauri can't find the sidecar. The error message is clear but easy to miss if you're not watching the build output carefully. Get the triple with `rustc -Vv | grep host`.
- Use a spec file rather than bare flags: PyInstaller spec files are the secret weapon. Real applications need custom specs that handle binary dependencies, data files, and hidden imports. Once you understand spec files, bundling Python apps becomes straightforward.
- Hook it as `beforeBuildCommand` in `tauri.conf.json` so `tauri build` can't forget it: forgetting to copy the executable to the binaries directory is surprisingly common. You rebuild the Python backend, forget to copy it, and wonder why your changes aren't working.
- **Dev mode:** add an env flag (`SIDECAR_DEV=1`) so Rust spawns `uv run uvicorn app.main:app --reload` instead of the binary — gives you Python hot reload without a PyInstaller cycle.
- **CI:** in the template's release matrix, add a `setup-python` + `build:sidecar` step per OS before `tauri-action` runs.

## 6. `AGENTS.md` — what to put in it

This file is for coding agents (Codex, Claude Code, Cursor, etc.), so it should tell them *how the project is wired and how to extend it without breaking the contract*. Proposed sections:

```markdown
# AGENTS.md

## Project overview
Tauri 2 desktop app. Frontend: Svelte 5 (runes) + shadcn-svelte + Tailwind.
Backend: Python 3.12 FastAPI sidecar, bundled with PyInstaller, spawned by Rust.
Frontend ↔ backend communication is HTTP on 127.0.0.1 with a bearer token.
Rust is ONLY for process lifecycle and native OS access — do not add business logic there.

## Where things live
- src/lib/api/client.ts — the only place that calls fetch(). Use it.
- src-python/app/scripts/ — all Python logic. One file per capability.
- src-python/app/routers/ — thin HTTP adapters. No logic here.
- src-tauri/src/sidecar.rs — spawn/health/shutdown. Rarely needs changes.

## How to add a new Python capability
1. Create src-python/app/scripts/<name>.py with Params, Result (Pydantic), NAME, DESCRIPTION, run().
2. It is auto-registered. Do not edit routers for this.
3. Regenerate TS types: `bun run gen:types` (pulls /openapi.json).
4. Add a Svelte component that calls api.runScript("<name>", params).
5. Write a test in src-python/tests/test_<name>.py.

## Commands
- `bun run dev`            — Tauri dev + uvicorn --reload (SIDECAR_DEV=1)
- `bun run build:sidecar`  — PyInstaller → src-tauri/binaries/
- `bun run build`          — full release build
- `uv run pytest`          — Python tests
- `bun run check`          — svelte-check + eslint

## Rules / conventions
- Svelte 5 runes only ($state, $derived, $props); no legacy stores or `export let`.
- Every FastAPI route except /health requires `Depends(verify_token)`.
- Long-running scripts (>2s) must use the jobs API and report progress().
- Never bind to 0.0.0.0. Never hardcode the port.
- Keep PyInstaller hidden imports in api_server.spec, not in code.
- shadcn components: `bunx shadcn-svelte@next add <component>`; don't hand-edit src/lib/components/ui.

## Gotchas
- Sidecar binary name must end with the Rust target triple.
- Killing the PyInstaller PID doesn't kill the child; use POST /shutdown first.
- After changing Python, rerun build:sidecar before testing a release build.
```

## 7. Suggested first milestone

1. Fork the template, get `bun run tauri dev` working.
2. Add `src-python/` with `/health` + one example script, run it manually with uvicorn.
3. Write `sidecar.rs` (spawn → READY handshake → managed state → shutdown).
4. Wire `client.ts` + one Svelte page that lists scripts and runs one.
5. Add the PyInstaller spec + `build:sidecar`, confirm a release build launches the bundled binary.
6. Add the jobs/SSE layer and AGENTS.md, then extend CI.

Good news: this is mostly already solved by Tauri's bundler — the `externalBin` sidecar gets packaged into whatever installer Tauri produces. But there are several sidecar‑specific and platform‑specific things you need to handle so the installed app actually works on a clean machine. Let me check the current state of Tauri 2's bundler and updater.Here's how shipping with an installer looks for this architecture.

## 1. What Tauri gives you out of the box

Tauri's bundler already produces native installers per OS; you don't need Electron‑builder‑style tooling. Tauri uses the MSI installer via the WiX Toolset v3 and the NSIS installer format for Windows, app bundles and DMG for macOS, and Debian/RPM packages and AppImage for Linux. Bundling Tauri applications for macOS, Windows, and Linux is supported with .app, .dmg, .deb, .rpm, .msi, .exe, and .AppImage targets, and cross-platform bundling is supported for Windows and Linux via Docker.

The sidecar rides along automatically: binaries declared in tauri.conf.json's externalBin are bundled into the target installer or archive, so on Windows they land next to your `.exe`, on macOS inside `Contents/MacOS/`, and Tauri resolves the path for you via the shell plugin's `sidecar()` API.

**Concretely, in `tauri.conf.json`:**

```jsonc
{
  "productName": "MyApp",
  "identifier": "com.yourorg.myapp",
  "bundle": {
    "active": true,
    "targets": ["nsis", "msi", "dmg", "deb", "rpm", "appimage"],
    "externalBin": ["binaries/api-server"],
    "icon": ["icons/icon.ico", "icons/icon.icns", "icons/128x128.png"],
    "windows": {
      "nsis": { "installMode": "perUser", "languages": ["English"] },
      "certificateThumbprint": null   // or use signCommand for Azure Trusted Signing
    },
    "macOS": { "minimumSystemVersion": "11.0" },
    "createUpdaterArtifacts": true
  }
}
```

Then `bun run tauri build` → installers appear in `src-tauri/target/release/bundle/`.

## 2. Sidecar‑specific things that break on a clean install

These are the issues that only surface once you run the installer on a machine that isn't your dev box:

| Problem | Fix |
|---|---|
| **PyInstaller `--onefile` extracts to `%TEMP%` on every launch** → 2–5s cold start, plus the “Tauri only knows the bootloader PID” kill problem from before | Use **`--onedir`** mode. The main executable goes in `externalBin`, and the `_internal/` folder goes in `bundle.resources`. Then set `cwd`/`sys._MEIPASS`‑relative paths accordingly. Startup drops to a few hundred ms and the PID you spawn is the real server. |
| **Missing system libs on user machines** (Linux `libssl`, Windows `vcruntime`) | PyInstaller bundles most; for Linux build on the *oldest* glibc you support (e.g. Ubuntu 22.04 in CI), or ship AppImage which is self‑contained. |
| **Antivirus/SmartScreen flags the PyInstaller exe** | Code‑sign both the Tauri exe *and* the sidecar exe (see §3). Avoid UPX compression in PyInstaller — it's the #1 false‑positive trigger. |
| **Writable data** — the install dir is read‑only (Program Files, `/Applications`) | Never write next to the binary. Rust passes `app.path().app_data_dir()` to Python as `--data-dir`; Python writes SQLite/logs/cache there. |
| **Port conflicts on user machines** | Already covered by the “bind to 127.0.0.1:0, print READY <port>” handshake — keep it. |
| **Firewall prompt on Windows** for the Python exe | Binding to `127.0.0.1` only (not `0.0.0.0`) avoids the Windows Firewall dialog. |
| **Orphaned Python process after crash/uninstall** | On startup, Rust writes the sidecar PID to app data; on next startup, kill any stale PID first. On Windows, additionally spawn with a Job Object (`CREATE_BREAKAWAY_FROM_JOB` off) so child dies with parent. |

## 3. Code signing & notarization (not optional for real users)

- **Windows:** unsigned installers get the SmartScreen “unrecognized app” wall. Options: an OV/EV certificate, or Azure Trusted Signing (cheapest for indie devs). Tauri supports a `signCommand` hook so you can sign with any tool. Crucially, sign the **sidecar exe too** — Tauri signs its own exe but you must sign `api-server-*.exe` in your `build:sidecar` step before bundling.
- **macOS:** Gatekeeper will refuse to run unsigned apps downloaded from the internet. You need an Apple Developer account ($99/yr), sign with a Developer ID cert, and notarize. Tauri handles this via env vars (`APPLE_CERTIFICATE`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`) in CI. The PyInstaller binary must also be signed with hardened runtime — add `codesign --force --options runtime --sign "$IDENTITY"` on the sidecar (and every `.so`/`.dylib` inside `_internal/`) in your build script, otherwise notarization fails.
- **Linux:** no signing required for `.deb`/`.rpm`/AppImage; optionally GPG‑sign the repo if you host one.

## 4. Auto‑updates

Since the sidecar is inside the bundle, an app update automatically updates the Python backend too — no separate update channel needed. The bundler can generate update bundles that can be used by the updater plugin. Setup:

1. `bun tauri add updater` + `bun tauri add process` (for relaunch).
2. `tauri signer generate` → keypair; public key goes in `plugins.updater.pubkey`, private key in CI secrets.
3. `createUpdaterArtifacts: true` (above) → produces `.sig` files and a `latest.json`.
4. Host `latest.json` on GitHub Releases (tauri‑action does this) or your own server; set `plugins.updater.endpoints`.
5. In Svelte, on startup: `check()` → show shadcn dialog “Update available” → `downloadAndInstall()` → `relaunch()`. Before relaunch, hit `POST /shutdown` so the old sidecar exits cleanly.

## 5. CI: one workflow, all installers

The template already has a release matrix with `tauri-action`. Add the sidecar step per OS:

```yaml
strategy:
  matrix:
    include:
      - platform: windows-latest
        target: x86_64-pc-windows-msvc
      - platform: macos-latest
        target: aarch64-apple-darwin
      - platform: macos-13          # intel
        target: x86_64-apple-darwin
      - platform: ubuntu-22.04      # oldest glibc you support
        target: x86_64-unknown-linux-gnu
steps:
  - uses: actions/checkout@v4
  - uses: astral-sh/setup-uv@v5
  - uses: oven-sh/setup-bun@v2
  - uses: dtolnay/rust-toolchain@stable
  - run: bun install
  - run: uv sync --project src-python
  - run: bun run build:sidecar -- --target ${{ matrix.target }}
  # (sign sidecar here on win/mac)
  - uses: tauri-apps/tauri-action@v0
    env:
      TAURI_SIGNING_PRIVATE_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}
      APPLE_CERTIFICATE: ${{ secrets.APPLE_CERTIFICATE }}
      # ...
    with:
      tagName: v__VERSION__
      releaseDraft: true
      includeUpdaterJson: true
```

Note: macOS needs two matrix entries (Intel + Apple Silicon) because PyInstaller can't cross‑compile — you can't build a universal binary of the Python sidecar the way Tauri can for Rust.

## 6. Test the installer, not just `tauri dev`

Add to `AGENTS.md` and your release checklist:

- Install on a **clean VM/machine** (no Python, no Rust). Windows Sandbox is perfect for this.
- Check: app launches in <2s, `/health` responds, a script runs, app data dir is created, closing the window leaves **no** `api-server` process in Task Manager.
- Uninstall → confirm no orphan process, decide whether to delete app data (NSIS lets you ask).
- Check the installer size; a FastAPI+uvicorn PyInstaller build is typically 30–60 MB, more if you pull in numpy/pandas. Use `--exclude-module` for stuff you don't need (tkinter, tests, etc.).

## 7. Additions to `AGENTS.md`

```markdown
## Packaging & release
- Sidecar is built in --onedir mode; exe → externalBin, _internal/ → bundle.resources.
- Python must never write next to its executable; use --data-dir passed by Rust.
- Sign the sidecar exe BEFORE `tauri build` (scripts/sign-sidecar.{ps1,sh}).
- Never enable UPX in the PyInstaller spec (AV false positives).
- Bump version in ONE place: package.json → synced to tauri.conf.json and pyproject.toml by `bun run version`.
- Release = push tag vX.Y.Z → CI builds nsis/msi/dmg/deb/rpm/AppImage + latest.json.
- Always test the built installer on a clean VM before publishing a release.
```


Here's the complete step-by-step setup, from empty folder to a working dev loop with the Python sidecar.

---

## Phase 0 — Prerequisites

Install in this order:

1. **Windows only:** MSVC first — if you are on Windows I also recommend installing MSVC before the other dependencies (make sure to check the "Desktop development with C++" workload). Linux needs the webkit deps: sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev.
2. **Rust:** `rustup` from rustup.rs.
3. **Bun:** `curl -fsSL https://bun.sh/install | bash` (or PowerShell installer on Windows).
4. **uv** (Python manager): `curl -LsSf https://astral.sh/uv/install.sh | sh` — it will fetch Python 3.12 for you.

Verify: `rustc -V`, `bun -v`, `uv --version`.

## Phase 1 — Get the template running

```bash
# Click "Use this template" on the GitHub repo, then:
git clone https://github.com/<you>/<your-app>.git
cd <your-app>
bun install
bun run tauri dev
```

A window should open with the shadcn demo UI. Don't continue until this works. Click the "Use this template" button on GitHub is the intended flow for this boilerplate. Add UI components as needed later: replace `<component>` with the name of the component you want to add (e.g., button, card, dialog); the full list is at next.shadcn-svelte.com/docs/components.

Also set your identity now in `src-tauri/tauri.conf.json`: `productName` and `identifier` (e.g. `com.yourorg.myapp`) — changing the identifier later invalidates user data paths.

## Phase 2 — Create the Python backend

```bash
mkdir src-python && cd src-python
uv init --name api-server --python 3.12
uv add fastapi "uvicorn[standard]" pydantic
uv add --dev pyinstaller pytest httpx
mkdir -p app/routers app/scripts app/core tests
```

**`app/core/config.py`** — reads what Rust passes in:

```python
import argparse, secrets

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=0)       # 0 = OS picks
    p.add_argument("--token", default=secrets.token_urlsafe(32))
    p.add_argument("--data-dir", default=".")
    return p.parse_args()
```

**`app/main.py`** — the entrypoint with the READY handshake:

```python
import sys, uvicorn
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import parse_args

args = parse_args()

def verify_token(authorization: str = Header("")):
    if authorization != f"Bearer {args.token}":
        raise HTTPException(401)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost:1420"],
    allow_methods=["*"], allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/shutdown", dependencies=[Depends(verify_token)])
async def shutdown():
    import asyncio, os, signal
    asyncio.get_event_loop().call_later(0.2, lambda: os.kill(os.getpid(), signal.SIGTERM))
    return {"status": "shutting down"}

# scripts router (auto-registered scripts) goes here, all with Depends(verify_token)

if __name__ == "__main__":
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", args.port))
    port = sock.getsockname()[1]
    print(f"READY {port}", flush=True)   # Rust waits for this line
    uvicorn.run(app, fd=None, host="127.0.0.1", port=port) if sock.close() is None else None
```

Add one example script in `app/scripts/example_task.py` (the `Params`/`Result`/`run()` shape from my first message) and a registry/router that exposes `GET /api/scripts` and `POST /api/scripts/{name}/run`.

**Test it standalone before touching Tauri:**

```bash
uv run python -m app.main --token devtoken
# → READY 54321
curl http://127.0.0.1:54321/health
```

## Phase 3 — Add the shell plugin to Tauri

```bash
cd .. # project root
bun run tauri add shell
```

This installs `tauri-plugin-shell` (Rust), `@tauri-apps/plugin-shell` (JS), and registers the plugin in `lib.rs`.

**`src-tauri/tauri.conf.json`:**

```jsonc
{
  "bundle": {
    "externalBin": ["binaries/api-server"]
  }
}
```

**`src-tauri/capabilities/default.json`** — permit *only* your sidecar. Use the shell:allow-spawn permission scoped to your binary with "sidecar": true:

```json
{
  "permissions": [
    "core:default",
    {
      "identifier": "shell:allow-spawn",
      "allow": [{ "name": "binaries/api-server", "sidecar": true }]
    }
  ]
}
```

You may see a warning in this file saying the folder isn't present — ignore it, it resolves once the binary exists.

## Phase 4 — Rust lifecycle code

**`src-tauri/src/sidecar.rs`** (sketch):

```rust
use tauri::{AppHandle, Manager};
use tauri_plugin_shell::{ShellExt, process::{CommandChild, CommandEvent}};
use std::sync::Mutex;

pub struct Backend { pub port: u16, pub token: String, pub child: Option<CommandChild> }

pub fn spawn(app: &AppHandle) -> tauri::Result<()> {
    let token = uuid::Uuid::new_v4().to_string();
    let data_dir = app.path().app_data_dir()?.to_string_lossy().to_string();

    let (mut rx, child) = app.shell()
        .sidecar("api-server").unwrap()
        .args(["--token", &token, "--data-dir", &data_dir])
        .spawn().expect("failed to spawn sidecar");

    let handle = app.clone();
    let tok = token.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            if let CommandEvent::Stdout(bytes) = event {
                let line = String::from_utf8_lossy(&bytes);
                if let Some(port) = line.strip_prefix("READY ") {
                    let port: u16 = port.trim().parse().unwrap();
                    handle.manage(Mutex::new(Backend { port, token: tok.clone(), child: None }));
                    handle.emit("backend-ready", port).ok();
                }
            }
        }
    });
    Ok(())
}

#[tauri::command]
pub fn get_backend(state: tauri::State<Mutex<Backend>>) -> (u16, String) {
    let b = state.lock().unwrap();
    (b.port, b.token.clone())
}
```

Call `sidecar::spawn(app.handle())` in `setup()`, register `get_backend`, and on `RunEvent::ExitRequested` POST `/shutdown` then kill as fallback. Two notes from people who've shipped this: the sidecar() function expects just the filename, NOT the whole path configured in the externalBin array, and store the CommandChild — you'll need it for clean shutdown — and don't trust spawn success; verify the process is actually doing its job (that's what the READY line + `/health` poll are for).

**Dev-mode branch:** if `SIDECAR_DEV=1`, spawn `uv run python -m app.main ...` with `Command::new` (dev only, not via capability) so you get Python hot-reload without PyInstaller.

## Phase 5 — Build the sidecar binary with the right name

This naming rule is the #1 setup failure: "externalBin": ["binaries/my-sidecar"] requires a src-tauri/binaries/my-sidecar-x86_64-unknown-linux-gnu executable on Linux or src-tauri/binaries/my-sidecar-aarch64-apple-darwin on Mac OS with Apple Silicon. Get your host's triple with `rustc --print host-tuple` (Rust 1.84+), or parse `rustc -Vv`.

**`scripts/build-sidecar.mjs`:**

```js
import { execSync } from "node:child_process";
import { cpSync, mkdirSync } from "node:fs";

const triple = execSync("rustc --print host-tuple").toString().trim();
const ext = process.platform === "win32" ? ".exe" : "";

execSync("uv run pyinstaller api_server.spec --noconfirm", { cwd: "src-python", stdio: "inherit" });

mkdirSync("src-tauri/binaries", { recursive: true });
cpSync(
  `src-python/dist/api-server/api-server${ext}`,
  `src-tauri/binaries/api-server-${triple}${ext}`
);
cpSync("src-python/dist/api-server/_internal", "src-tauri/resources/_internal", { recursive: true });
```

Wire into **`package.json`**:

```json
{
  "scripts": {
    "build:sidecar": "node scripts/build-sidecar.mjs",
    "dev": "cross-env SIDECAR_DEV=1 tauri dev",
    "build": "bun run build:sidecar && tauri build"
  }
}
```

And add `"resources": ["resources/_internal"]` under `bundle` in `tauri.conf.json` (onedir mode, per the installer discussion). Gitignore `src-tauri/binaries/` and `src-tauri/resources/_internal/`.

## Phase 6 — Frontend wiring

```bash
bun add -d openapi-typescript   # optional: type generation from /openapi.json
```

**`src/lib/api/backend.svelte.ts`:**

```ts
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

let port = $state(0);
let token = $state("");
export const backend = {
  get ready() { return port > 0; },
  get base() { return `http://127.0.0.1:${port}`; },
  get headers() { return { Authorization: `Bearer ${token}` }; },
  async init() {
    await listen<number>("backend-ready", (e) => { port = e.payload; });
    try { [port, token] = await invoke<[number, string]>("get_backend"); } catch {}
  },
};
```

Call `backend.init()` in the root `+layout.svelte`, then build a page that fetches `GET /api/scripts` and renders a form per script.

## Phase 7 — Verify the full loop

```bash
# Dev loop (Python via uvicorn, hot reload both sides)
bun run dev

# Production-shaped loop (real PyInstaller binary)
bun run build:sidecar
bun run tauri dev          # without SIDECAR_DEV → uses the binary

# Full installer
bun run build              # → src-tauri/target/release/bundle/
```

Checklist per stage: window opens → `backend-ready` fires → scripts page lists your example task → running it returns a result → closing the app leaves no `api-server` process running.

## Phase 8 — Finish

1. Drop in the `AGENTS.md` from my first message (plus the packaging section from the second).
2. Extend the template's CI matrix with the `setup-uv` + `build:sidecar` steps (from the installer answer).
3. Only then: signing, updater, release tags.

---

**Order matters:** the most common way this goes wrong is doing Phase 5 before Phase 2's standalone test passes, or fighting Tauri capability errors that are actually just the missing target-triple suffix. If you hit a wall, the first three things to check are: binary name suffix, capability `name` matching `externalBin` exactly, and whether `READY` is actually printed with `flush=True`.

