import subprocess
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent
main_script = repo_root / "log_generator" / "main.py"

process = subprocess.Popen(
    [sys.executable, str(main_script)],
    cwd=str(repo_root),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

stdout, stderr = process.communicate()

if stdout:
    print(stdout)
if stderr:
    print(stderr)
    