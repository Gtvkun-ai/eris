import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "src" / "vscode-extension"


def load_manifest():
    return json.loads((EXT / "package.json").read_text(encoding="utf-8"))


def test_manifest_is_eris_branded_gitpilot_distribution():
    manifest = load_manifest()
    commands = {item["command"] for item in manifest["contributes"]["commands"]}
    settings = manifest["contributes"]["configuration"]["properties"]
    source = (EXT / "src" / "extension.ts").read_text(encoding="utf-8")

    assert manifest["name"] == "eris-code"
    assert "GitPilot" in manifest["displayName"]
    assert manifest["main"] == "./out/extension.js"
    assert "gitpilot.openChat" in commands
    assert "gitpilot.setPermissionMode" in commands
    assert 'registerCommand("gitpilot.applyProposedChanges"' in source
    assert "gitpilot.serverUrl" in settings
    assert "gitpilot.permissionMode" in settings
    assert "erisCode.erisLink.enabled" in settings


def test_native_gitpilot_entrypoint_and_resources_are_present():
    assert (EXT / "src" / "extension.ts").is_file()
    assert (EXT / "resources" / "icon.svg").is_file()
    assert (EXT / "resources" / "icon.png").is_file()


def test_old_eris_adapter_is_not_the_active_entrypoint():
    manifest = load_manifest()
    assert manifest["main"] != "./dist/extension.js"
    assert not (EXT / "src" / "chatPanel.ts").is_file()
    assert not (EXT / "src" / "gitPilotClient.ts").is_file()


def test_vsix_contains_native_out_and_resources():
    vsix_files = sorted(EXT.glob("eris-code-*.vsix"))
    assert vsix_files, "a packaged Eris VSIX is required for this contract"
    with zipfile.ZipFile(vsix_files[-1]) as archive:
        names = set(archive.namelist())
    assert "extension/package.json" in names
    assert "extension/out/extension.js" in names
    assert "extension/out/ui/webview/gitpilotWorkspaceTemplate.html" in names
    assert "extension/resources/icon.svg" in names
