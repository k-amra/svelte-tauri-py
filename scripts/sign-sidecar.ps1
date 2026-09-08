# Sign the sidecar exe BEFORE `tauri build` (Windows).
# Requires: Azure Trusted Signing or an OV/EV code-signing cert.
# Usage: powershell -File scripts/sign-sidecar.ps1
# See plan.md installer §3: Tauri signs its own exe, you must sign api-server-*.exe yourself.
param(
  [string]$Triple = (rustc --print host-tuple).Trim()
)
$exe = "src-tauri/binaries/api-server-$Triple.exe"
if (-not (Test-Path $exe)) { Write-Error "Missing $exe — run build:sidecar first"; exit 1 }
if (-not $env:SIGN_COMMAND) {
  if ($env:SIGNING_REQUIRED -eq '1') {
    Write-Error "SIGN_COMMAND not set and SIGNING_REQUIRED=1 — refusing to ship an unsigned sidecar."
    exit 1
  }
  Write-Warning "SIGN_COMMAND not set — skipping sidecar signing (unsigned builds trigger SmartScreen)."
  exit 0
}
& $env:SIGN_COMMAND $exe
