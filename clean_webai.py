import re
with open('_fullbuild.py', 'r') as f:
    txt = f.read()

txt = re.sub(r'"echo \[OK\]   WebAI-to-API UP at http://localhost:8081",\s*"",\s*":: Step 3: Start Eris",\s*', '', txt)
txt = txt.replace('"echo  WebAI UI: http://localhost:8081/ui",', '')

# Remove webai deployment logic
txt = re.sub(r'# Tao _start_webai\.bat.*?start_webai_content = \(.*?\)[\r\n\s]+with open\(start_webai_path, "wb"\) as fh:.*?print\("  \[OK\] _start_webai\.bat.*?"\)', '', txt, flags=re.DOTALL)

with open('_fullbuild.py', 'w') as f:
    f.write(txt)
