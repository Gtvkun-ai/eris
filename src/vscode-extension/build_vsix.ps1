$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $Root "scripts\sync-upstream.ps1")

Push-Location $Root
try {
  npm.cmd install --no-audit --no-fund
  npm.cmd run compile
  python package_vsix.py
} finally {
  Pop-Location
}
