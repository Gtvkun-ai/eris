#!/usr/bin/env sh
set -eu
python3.12 -m pip install --upgrade -r "$(dirname "$0")/../runtime/requirements-gitpilot.txt"
gitpilot doctor
echo "GitPilot installed. Configure its OpenAI provider, then run: gitpilot serve"
