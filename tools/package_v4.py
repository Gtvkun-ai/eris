# -*- coding: utf-8 -*-
"""Đóng gói V4 từ source V3 + những file nâng cấp, bỏ cache/log/key/secret."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
out = Path('/mnt/data')
changed = [
 'src/runtime/workspace/__init__.py',
 'src/runtime/workspace/math_worker.py',
 'src/runtime/workspace/math_artifacts.py',
 'src/runtime/workspace/python_docker.py',
 'src/body/UdpListener.ArtifactWorkspace.cs',
 'src/body/UdpListener.cs',
 'src/actions/contracts.py',
 'src/actions/capability_registry.py',
 'src/actions/executor.py',
 'src/actions/capability_runtime.py',
 'src/tests/workspace/test_math_workspace_v4.py',
 'tools/math_workspace_probe.py',
 'requirements-artifact-workspace.txt',
 'README_V4_MATH_WORKSPACE_TIENG_VIET.md',
]
for name,files in (
    ('Eris_V4_Math_Artifact_Overlay.zip', [root/x for x in changed]),
    ('Eris_V4_Math_Artifact_Full_Source.zip', [x for x in root.rglob('*') if x.is_file()]),
):
    count=0; skipped=[]
    with zipfile.ZipFile(out/name, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for file in files:
            rel=file.relative_to(root)
            parts=rel.parts
            if any(p in {'.git','.pytest_cache','__pycache__','logs','.venv','node_modules','.mypy_cache','dist','.godot'} for p in parts): continue
            if rel.suffix in {'.pyc','.sqlite','.db','.pyo'}: continue
            if str(rel).startswith('tools/whale2api/') and ('vendor' in parts or '.cache' in parts): continue
            if file.name.startswith('.env') and file.name != '.env.example': continue
            try:
                str(rel).encode('utf-8', 'strict')
                z.write(file, rel.as_posix())
                count+=1
            except (UnicodeError, OSError) as e:
                skipped.append((str(rel),str(e)))
    with zipfile.ZipFile(out/name) as z:
        assert z.testzip() is None
    print(name, 'files', count, 'bytes', (out/name).stat().st_size, 'skip',len(skipped))
    if skipped: print(skipped[:5])
