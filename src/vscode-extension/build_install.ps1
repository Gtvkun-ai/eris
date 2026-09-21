$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $Root "build_vsix.ps1")

$Vsix = Get-ChildItem -LiteralPath $Root -Filter "eris-code-*.vsix" -File |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
if (-not $Vsix) {
  throw "No Eris GitPilot VSIX was produced."
}

$Code = Get-Command code -ErrorAction SilentlyContinue
if (-not $Code) {
  throw "VSIX built at $($Vsix.FullName), but the VS Code 'code' CLI is not on PATH."
}

& $Code.Source --install-extension $Vsix.FullName --force
if ($LASTEXITCODE -ne 0) {
  throw "VS Code failed to install $($Vsix.FullName)."
}

Write-Host "Installed $($Vsix.FullName)"
