$ErrorActionPreference = "Stop"

# Build sạch để type-check bằng dependency thật trên máy dev, rồi đóng gói VSIX.
# package_vsix.py không cần @vscode/vsce nên ít thêm một dependency build vô nghĩa.
npm install --no-audit --no-fund
npm run compile
python package_vsix.py
