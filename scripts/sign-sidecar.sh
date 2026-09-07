#!/usr/bin/env bash
# Sign the sidecar (+ every .so/.dylib inside _internal/) BEFORE `tauri build` (macOS).
# Requires Developer ID cert + hardened runtime, otherwise notarization fails.
# Usage: IDENTITY="Developer ID Application: ..." scripts/sign-sidecar.sh
set -euo pipefail
TRIPLE="${1:-$(rustc --print host-tuple)}"
EXE="src-tauri/binaries/api-server-${TRIPLE}"
if [[ ! -f "$EXE" ]]; then echo "Missing $EXE — run build:sidecar first" >&2; exit 1; fi
if [[ -z "${IDENTITY:-}" ]]; then echo "IDENTITY not set — skipping sidecar signing."; exit 0; fi
codesign --force --options runtime --sign "$IDENTITY" "$EXE"
if [[ -d "src-tauri/resources/_internal" ]]; then
  find "src-tauri/resources/_internal" -name "*.so" -o -name "*.dylib" | while read -r f; do
    codesign --force --options runtime --sign "$IDENTITY" "$f"
  done
fi
echo "Signed $EXE"
