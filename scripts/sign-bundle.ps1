# Sign a Tauri Windows bundle artifact (exe/msi) produced by `tauri build`.
# Invoked via tauri.conf.json `bundle.windows.signCommand` with %1 = target path.
# Requires: Azure Trusted Signing or an OV/EV code-signing cert.
#
# SIGN_COMMAND contract (same as scripts/sign-sidecar.ps1):
#   Must be a COMMAND LINE, not just a binary path. It is tokenized on
#   whitespace and the target path is appended as the final argument.
param(
  [string]$Target
)
if (-not $Target) { Write-Error "Missing target path argument (%1)."; exit 1 }
if (-not (Test-Path $Target)) { Write-Error "Missing $Target."; exit 1 }
if (-not $env:SIGN_COMMAND) {
  if ($env:SIGNING_REQUIRED -eq '1') {
    Write-Error "SIGN_COMMAND not set and SIGNING_REQUIRED=1 — refusing to ship an unsigned bundle."
    exit 1
  }
  Write-Warning "SIGN_COMMAND not set — skipping bundle signing (unsigned builds trigger SmartScreen)."
  exit 0
}
# Tokenize: `& "a b c" arg` treats the whole string as a command name and fails.
# Split on whitespace, then re-invoke with the target appended.
$parts = @($env:SIGN_COMMAND -split '\s+' | Where-Object { $_ -ne '' })
if ($parts.Count -eq 0) {
  Write-Error "SIGN_COMMAND is empty after tokenization."
  exit 1
}
$rest = @()
if ($parts.Count -gt 1) {
  $rest = @($parts[1..($parts.Count - 1)])
}
& $parts[0] @rest $Target
if ($LASTEXITCODE -ne 0) {
  Write-Error "SIGN_COMMAND exited with code $LASTEXITCODE — bundle artifact is NOT signed: $Target."
  exit $LASTEXITCODE
}
