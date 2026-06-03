import json
import subprocess
import sys

d = json.loads(sys.stdin.read())
f = d.get("tool_input", {}).get("file_path", "")

if not f or not f.endswith(".py"):
    sys.exit(0)

subprocess.run([sys.executable, "-m", "ruff", "check", "--fix", f], check=False)
result = subprocess.run(
    [sys.executable, "-m", "mypy", f, "--ignore-missing-imports", "--no-error-summary"],
    capture_output=True,
    text=True,
    check=False,
)
out = (result.stdout + result.stderr).strip()
if out:
    print("\n".join(out.split("\n")[-5:]))
