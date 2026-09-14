# Sign the sidecar exe BEFORE `tauri build` (Windows).
# Requires: Azure Trusted Signing or an OV/EV code-signing cert.
# Usage: powershell -File scripts/sign-sidecar.ps1
# See plan.md installer §3: Tauri signs its own exe, you must sign api-server-*.exe yourself.
#
# SIGN_COMMAND contract (read this):
#   Must be a COMMAND LINE, not just a binary path. It is tokenized on
#   whitespace and the exe is appended as the final argument. For signtool:
#     SIGN_COMMAND = 'signtool.exe sign /fd sha256 /tr http://timestamp.digicert.com /td sha256'
#   For Azure Trusted Signing:
#     SIGN_COMMAND = 'AzureSignTool.exe sign -kvu https://... -kvc ... -tr ...'
#   If your invocation needs quoting that survives whitespace tokenization,
#   point SIGN_COMMAND at a wrapper script that takes the exe as $args[0].
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
# Tokenize: `& "a b c" arg` treats the whole string as a command name and fails.
# Split on whitespace, then re-invoke with the exe appended.
$parts = $env:SIGN_COMMAND -split '\s+' | Where-Object { $_ -ne '' }
if ($parts.Count -eq 0) {
  Write-Error "SIGN_COMMAND is empty after tokenization."
  exit 1
}
& $parts[0] @($parts[1..($parts.Count - 1)]) $exe
if ($LASTEXITCODE -ne 0) {
  Write-Error "SIGN_COMMAND exited with code $LASTEXITCODE — sidecar is NOT signed."
  exit $LASTEXITCODE
}
