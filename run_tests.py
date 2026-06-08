import subprocess, sys, os

env = {**os.environ, 'PYTHONPATH': 'src'}
result = subprocess.run(
    [sys.executable, '-m', 'pytest', 'tests/', '--tb=line', '-q', '--no-header'],
    capture_output=True, text=True, cwd=r'c:\Users\Gtvkun\Documents\GitHub\eris',
    env=env, timeout=300
)
output = result.stdout + result.stderr
lines = output.splitlines()

# Collect FAILED lines and summary lines
failures = [l for l in lines if l.startswith('FAILED') or l.startswith('ERROR ')]
summary_lines = [l for l in lines[-20:] if l.strip()]

print("=== FAILURES ===")
for f in failures:
    print(f)
print(f"\nTotal failures: {len(failures)}")
print("\n=== SUMMARY (last lines) ===")
for l in summary_lines:
    print(l)
