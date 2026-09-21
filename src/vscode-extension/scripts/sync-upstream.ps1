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
Copy-Item (Join-Path $Upstream "resources\*") (Join-Path $Destination "resources") -Recurse -Force
Copy-Item (Join-Path $Upstream "scripts\copy-webview-assets.js") (Join-Path $Destination "scripts\copy-webview-assets.js") -Force
Copy-Item (Join-Path $Upstream "tsconfig.json") (Join-Path $Destination "tsconfig.json") -Force
Copy-Item (Join-Path $Upstream ".vscodeignore") (Join-Path $Destination ".vscodeignore") -Force
New-Item -ItemType Directory -Force (Join-Path $Destination "src\eris") | Out-Null
Get-ChildItem -LiteralPath $ErisAdapter -Filter "*.ts" -File | Copy-Item -Destination (Join-Path $Destination "src\eris") -Force

$TsConfigPath = Join-Path $Destination "tsconfig.json"
$TsConfig = Get-Content -Raw $TsConfigPath | ConvertFrom-Json
$Excluded = @($TsConfig.exclude)
if ($Excluded -notcontains "eris") {
  $TsConfig.exclude = @($Excluded + "eris")
  $Json = $TsConfig | ConvertTo-Json -Depth 20
  [System.IO.File]::WriteAllText($TsConfigPath, $Json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}

$Entrypoint = Join-Path $Destination "src\extension.ts"
$Source = Get-Content -Raw $Entrypoint
$ImportAnchor = 'import { ProjectIndexCache } from "./services/context/projectIndexCache";'
$ImportPatch = @"
$ImportAnchor
import { CompanionWorkspaceObserver, registerExternalAgentObservationBridge } from "./eris/companionWorkspaceObserver";
import { ErisObserverBridge } from "./eris/erisObserverBridge";
"@
if (-not $Source.Contains($ImportAnchor)) {
  throw "GitPilot extension import anchor changed; update the Eris sync patch."
}
$Source = $Source.Replace($ImportAnchor, $ImportPatch.TrimEnd())

$ActivationAnchor = '  const output = vscode.window.createOutputChannel(OUTPUT_CHANNEL_NAME);'
$ActivationPatch = @"
$ActivationAnchor

  const erisLinkEnabled = vscode.workspace
    .getConfiguration("erisCode.erisLink")
    .get<boolean>("enabled", false);
  const erisBridge = new ErisObserverBridge();
  if (erisLinkEnabled) {
    context.subscriptions.push(new CompanionWorkspaceObserver(erisBridge));
    registerExternalAgentObservationBridge(context, erisBridge);
  }
"@
if (-not $Source.Contains($ActivationAnchor)) {
  throw "GitPilot extension activation anchor changed; update the Eris sync patch."
}
$Source = $Source.Replace($ActivationAnchor, $ActivationPatch.TrimEnd())
[System.IO.File]::WriteAllText($Entrypoint, $Source, [System.Text.UTF8Encoding]::new($false))

Write-Host "Synced GitPilot extension source from $Upstream"
