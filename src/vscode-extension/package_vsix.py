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
DIST_ENTRY = DIST / "extension.js"
SRC = ROOT / "src"
MEDIA = ROOT / "media"

# Chỉ đóng gói asset thực sự được extension sử dụng.
# media/chatPanel.js là UI legacy. Webview 0.13 chỉ đóng gói shell mới
# eris-chat.css/js để không tồn tại hai presentation layer cùng lúc trong VSIX.
MEDIA_ALLOWLIST = {"eris.svg", "eris-chat.css", "eris-chat.js"}


def main() -> int:
    if not PACKAGE.is_file():
        raise SystemExit("Thiếu package.json")
    if not DIST_ENTRY.is_file():
        raise SystemExit("Thiếu dist/extension.js. Hãy chạy npm run compile trước.")

    # V90 vẫn ưu tiên bundle esbuild một-file. Tuy nhiên release packer cũng chấp
    # nhận output CommonJS sạch từ `tsc` (hữu ích ở môi trường build không có native
    # esbuild binary). Multi-file mode chỉ hợp lệ khi tập .js khớp CHÍNH XÁC tập
    # source .ts, nên stale JS vẫn không thể lọt vào VSIX.
    dist_js = sorted(path.relative_to(DIST) for path in DIST.rglob("*.js") if path.is_file())
    expected_tsc_js = sorted(path.relative_to(SRC).with_suffix(".js") for path in SRC.rglob("*.ts") if path.is_file())
    bundle_mode = dist_js == [Path("extension.js")]
    tsc_mode = dist_js == expected_tsc_js
    if not bundle_mode and not tsc_mode:
        raise SystemExit(
            "dist/ không khớp bundle sạch hoặc tsc sạch. Hãy xóa dist rồi build lại.\n"
            f"dist_js={len(dist_js)} expected_tsc_js={len(expected_tsc_js)}"
        )

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
  <Default Extension="css" ContentType="text/css" />
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
        if bundle_mode:
            archive.write(DIST_ENTRY, "extension/dist/extension.js")
        else:
            for rel in dist_js:
                archive.write(DIST / rel, f"extension/dist/{rel.as_posix()}")

        # media/ được allowlist rõ ràng để không vô tình mang UI/asset cũ vào VSIX.
        if MEDIA.exists():
            for media_name in sorted(MEDIA_ALLOWLIST):
                path = MEDIA / media_name
                if path.is_file():
                    rel = path.relative_to(ROOT).as_posix()
                    archive.write(path, f"extension/{rel}")

    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
