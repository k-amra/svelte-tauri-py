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

# polars ships a compiled extension (polars.polars): collect everything
# explicitly so frozen-mode discovery can't silently miss it.
polars_datas, polars_binaries, polars_hiddenimports = collect_all('polars')

block_cipher = None

a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=polars_binaries,
    datas=polars_datas,
    hiddenimports=[
        'httpx',
        'app.services',
        'app.routers.harambelogs',
        'app.services.harambelogs_client',
        'app.services.harambelogs_models',
        'app.services.log_cache',
        'app.services.emotes',
        'app.services.log_fetch',
        'app.scripts.chat_stats',
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
        'app.scripts.example_task',
        *polars_hiddenimports,
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
