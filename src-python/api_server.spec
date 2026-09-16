# PyInstaller spec (ONEFILE mode).
#
# Why onefile and not onedir: Tauri's `externalBin` bundles single files only,
# and the onedir bootloader requires its `_internal/` directory as a sibling of
# the exe. Tauri ships `resources/` in a different directory than the sidecar
# exe (verified: `target/release/api-server.exe` dies with
# "Failed to load Python DLL '.../_internal/python312.dll'"), so onedir can
# never work here. Onefile = one exe, works from any directory.
#
# Trade-offs vs onedir (accepted deliberately):
# - Cold start is 2-5s (extracts to %TEMP% on every launch). The UI shows
#   backend status meanwhile, so this is visible, not broken.
# - Tauri only knows the bootloader PID, not the real server PID. Our shutdown
#   design already handles this: POST /shutdown is the PRIMARY mechanism
#   (the server kills itself), kill() is only the fallback. See sidecar.rs.
#
# Layout after build:
#   dist/api-server(.exe) -> copied to src-tauri/binaries/api-server-<triple>(.exe)
#
# NEVER enable UPX (AV false positives). Keep hidden imports here, not in code.

# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

import os
import ast

# polars ships a compiled extension (polars.polars): collect everything
# explicitly so frozen-mode discovery can't silently miss it.
polars_datas, polars_binaries, polars_hiddenimports = collect_all('polars')
# tzdata supplies the IANA database for zoneinfo on Windows: without it any
# tz-aware polars -> Python conversion (iter_rows, min(), to_list() on a
# Datetime(time_zone=...) column) raises ZoneInfoNotFoundError.
try:
    tzdata_datas, tzdata_binaries, tzdata_hiddenimports = collect_all('tzdata')
except Exception:
    tzdata_datas, tzdata_binaries, tzdata_hiddenimports = [], [], []

# Scripts are discovered via FROZEN_SCRIPTS in frozen_scripts.py, which
# registry.py imports at runtime. Parse that file directly (instead of
# importing it) so the spec never pulls the app package into the build
# environment here. PyInstaller exec()s the spec without __file__ but with
# SPECPATH set to the spec's directory (which is also the CWD when built
# via `bun run build:sidecar`); fall back through both.
def _spec_dir():
    # PyInstaller exec()s the spec, so `__file__` is usually undefined;
    # SPECPATH points at the spec's directory. Try SPECPATH first to avoid
    # paying the NameError on every build.
    # Newer PyInstaller exposes SPECPATH as a list; take the first entry.
    sp = globals().get("SPECPATH")
    if isinstance(sp, (list, tuple)):
        sp = sp[0] if sp else None
    candidates = [sp]
    try:
        candidates.append(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
    candidates.append(os.getcwd())
    for candidate in candidates:
        if candidate and os.path.isfile(os.path.join(candidate, "frozen_scripts.py")):
            return candidate
    return os.getcwd()


_frozen_path = os.path.join(_spec_dir(), "frozen_scripts.py")
with open(_frozen_path, "r", encoding="utf-8") as f:
    _tree = ast.parse(f.read())
_frozen_scripts: list[str] = []
for node in _tree.body:
    if (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "FROZEN_SCRIPTS"
        and isinstance(node.value, ast.Tuple)
    ):
        _frozen_scripts = [ast.literal_eval(el) for el in node.value.elts]
        break
if not _frozen_scripts:
    raise RuntimeError("could not read FROZEN_SCRIPTS from frozen_scripts.py")

block_cipher = None

a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=polars_binaries + tzdata_binaries,
    datas=polars_datas + tzdata_datas,
    hiddenimports=[
        'httpx',
        'app.services',
        'app.routers.harambelogs',
        'app.services.harambelogs_client',
        'app.services.harambelogs_models',
        'app.services.log_cache',
        'app.services.emotes',
        'app.services.log_fetch',
        # Scripts are discovered via FROZEN_SCRIPTS in frozen_scripts.py,
        # which registry.py imports at runtime. Add them explicitly here
        # because PyInstaller cannot see the dynamic import_module() call.
        *[f'app.scripts.{name}' for name in _frozen_scripts],
        'frozen_scripts',   # the module itself must be bundled
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'app.main',
        'app.core.config',
        'app.core.jobs',
        'app.core.paths',
        'app.routers.scripts',
        'app.routers.jobs',
        'app.scripts.registry',
        *polars_hiddenimports,
        *tzdata_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'Tkinter',
        'unittest',
        'test',
        'pytest',
        '_pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='api-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # NEVER enable UPX — #1 AV false-positive trigger
    console=True,  # MUST stay True: Rust reads the READY line from stdout
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
