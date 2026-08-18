#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Đóng gói Eris VS Code extension thành VSIX không cần cài @vscode/vsce.

Script chỉ đóng gói artifact đã compile trong dist/. Compile vẫn nên chạy bằng
`npm run compile` ở máy dev để có type-check đầy đủ trước khi phát hành.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "package.json"
DIST = ROOT / "dist"
MEDIA = ROOT / "media"


def main() -> int:
    if not PACKAGE.is_file():
        raise SystemExit("Thiếu package.json")
    if not (DIST / "extension.js").is_file():
        raise SystemExit("Thiếu dist/extension.js. Hãy chạy npm run compile trước.")

    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    name = str(package.get("name") or "eris-vscode")
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
  <Default Extension="map" ContentType="application/json" />
  <Default Extension="svg" ContentType="image/svg+xml" />
  <Default Extension="vsixmanifest" ContentType="text/xml" />
</Types>
"""
    manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
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

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("extension.vsixmanifest", manifest)
        archive.write(PACKAGE, "extension/package.json")
        for base in (DIST, MEDIA):
            if not base.exists():
                continue
            for path in sorted(item for item in base.rglob("*") if item.is_file()):
                rel = path.relative_to(ROOT).as_posix()
                archive.write(path, f"extension/{rel}")

    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
