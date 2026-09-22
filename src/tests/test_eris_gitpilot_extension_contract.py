import json
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


def test_vsix_packager_includes_native_out_and_resources():
    packer = (EXT / "package_vsix.py").read_text(encoding="utf-8")
    build_script = (EXT / "build_vsix.ps1").read_text(encoding="utf-8")

    assert 'files = [(PACKAGE, "extension/package.json")]' in packer
    assert 'package_files(OUT, "out"' in packer
    assert 'package_files(RESOURCES, "resources"' in packer
    assert 'workspace_template = OUT / "ui" / "webview" / "gitpilotWorkspaceTemplate.html"' in packer
    assert "python package_vsix.py" in build_script


def test_vsce_ignores_eris_adapter_staging_source():
    ignore = (EXT / ".vscodeignore").read_text(encoding="utf-8")
    assert "eris/**" in ignore
