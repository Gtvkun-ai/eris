#!/usr/bin/env python3
"""Package the branded native GitPilot extension as a VSIX."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr


ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "package.json"
OUT = ROOT / "out"
RESOURCES = ROOT / "resources"


def load_package() -> dict:
    if not PACKAGE.is_file():
        raise SystemExit("Missing package.json")
    return json.loads(PACKAGE.read_text(encoding="utf-8"))


def package_files(root: Path, prefix: str, allowed_suffixes: set[str]) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in allowed_suffixes:
            files.append((path, f"extension/{prefix}/{path.relative_to(root).as_posix()}"))
    return files


def main() -> int:
    package = load_package()
    entrypoint = OUT / "extension.js"
    workspace_template = OUT / "ui" / "webview" / "gitpilotWorkspaceTemplate.html"
    if not entrypoint.is_file() or not workspace_template.is_file():
        raise SystemExit("Missing native GitPilot build output. Run npm.cmd run compile first.")
    if not (RESOURCES / "icon.svg").is_file() or not (RESOURCES / "icon.png").is_file():
        raise SystemExit("Missing extension resources.")

    name = str(package.get("name") or "eris-code")
    publisher = str(package.get("publisher") or "gtvk")
    version = str(package.get("version") or "0.0.0")
    display_name = str(package.get("displayName") or name)
    description = str(package.get("description") or "")
    vscode_engine = str((package.get("engines") or {}).get("vscode") or "*")
    categories = package.get("categories") or ["Other"]
    categories_text = ",".join(str(item) for item in categories if str(item).strip()) or "Other"
    output = ROOT / f"{name}-{version}.vsix"

    content_types = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="json" ContentType="application/json" />
  <Default Extension="js" ContentType="application/javascript" />
  <Default Extension="css" ContentType="text/css" />
  <Default Extension="html" ContentType="text/html" />
  <Default Extension="map" ContentType="application/json" />
  <Default Extension="svg" ContentType="image/svg+xml" />
  <Default Extension="png" ContentType="image/png" />
  <Default Extension="vsixmanifest" ContentType="text/xml" />
</Types>
"""
    manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0" xmlns="http://schemas.microsoft.com/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id={quoteattr(name)} Version={quoteattr(version)} Publisher={quoteattr(publisher)} />
    <DisplayName>{escape(display_name)}</DisplayName>
    <Description xml:space="preserve">{escape(description)}</Description>
    <Categories>{escape(categories_text)}</Categories>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value={quoteattr(vscode_engine)} />
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code" />
  </Installation>
  <Dependencies />
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
  </Assets>
</PackageManifest>
"""

    files = [(PACKAGE, "extension/package.json")]
    files.extend(package_files(OUT, "out", {".js", ".map", ".html", ".css", ".json"}))
    files.extend(package_files(RESOURCES, "resources", {".svg", ".png"}))

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("extension.vsixmanifest", manifest)
        for path, archive_name in files:
            archive.write(path, archive_name)

    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
