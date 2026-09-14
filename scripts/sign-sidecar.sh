#!/usr/bin/env bash
# Sign the onefile sidecar BEFORE `tauri build` (macOS).
# Requires Developer ID cert + hardened runtime, otherwise notarization fails.
# Usage: IDENTITY="Developer ID Application: ..." scripts/sign-sidecar.sh
set -euo pipefail

# Mirror build-sidecar.mjs: `--print host-tuple` requires Rust >= 1.84; parse
# `rustc -Vv` for older toolchains (Cargo.toml allows 1.77.2).
detect_triple() {
  if rustc --print host-tuple >/dev/null 2>&1; then
    rustc --print host-tuple
  else
    rustc -Vv | sed -n 's/^host: //p'
  fi
}

TRIPLE="${1:-$(detect_triple)}"
EXE="src-tauri/binaries/api-server-${TRIPLE}"
if [[ ! -f "$EXE" ]]; then echo "Missing $EXE — run build:sidecar first" >&2; exit 1; fi
if [[ -z "${IDENTITY:-}" ]]; then
  if [[ "${SIGNING_REQUIRED:-}" == "1" ]]; then
    echo "IDENTITY not set and SIGNING_REQUIRED=1 — refusing to ship an unsigned sidecar." >&2
    exit 1
  fi
  echo "IDENTITY not set — skipping sidecar signing."
  exit 0
fi
codesign --force --options runtime --sign "$IDENTITY" "$EXE"
echo "Signed $EXE"
