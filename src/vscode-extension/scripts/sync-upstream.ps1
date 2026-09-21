$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$Upstream = Join-Path $RepoRoot "services\gitpilot\extensions\vscode"
$Destination = Join-Path $RepoRoot "src\vscode-extension"
$ErisAdapter = Join-Path $Destination "eris"

if (-not (Test-Path (Join-Path $Upstream "src\extension.ts"))) {
  throw "Vendored GitPilot extension source is missing."
}

if (-not (Test-Path (Join-Path $ErisAdapter "erisObserverBridge.ts"))) {
  throw "Eris adapter source is missing from $ErisAdapter."
}

Remove-Item (Join-Path $Destination "src") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $Destination "test") -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Upstream "src") (Join-Path $Destination "src") -Recurse -Force
Copy-Item (Join-Path $Upstream "test") (Join-Path $Destination "test") -Recurse -Force
Copy-Item (Join-Path $Upstream "resources") (Join-Path $Destination "resources") -Recurse -Force
Copy-Item (Join-Path $Upstream "scripts\copy-webview-assets.js") (Join-Path $Destination "scripts\copy-webview-assets.js") -Force
Copy-Item (Join-Path $Upstream "tsconfig.json") (Join-Path $Destination "tsconfig.json") -Force
Copy-Item (Join-Path $Upstream ".vscodeignore") (Join-Path $Destination ".vscodeignore") -Force
Copy-Item $ErisAdapter (Join-Path $Destination "src\eris") -Recurse -Force

Write-Host "Synced GitPilot extension source from $Upstream"
