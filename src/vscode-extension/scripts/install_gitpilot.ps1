$ErrorActionPreference = "Stop"
py -3.12 -m pip install --upgrade -r "$PSScriptRoot\..\runtime\requirements-gitpilot.txt"
gitpilot doctor
Write-Host "GitPilot installed. Configure its OpenAI provider, then run: gitpilot serve"
