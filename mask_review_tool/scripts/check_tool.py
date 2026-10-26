"""Run portable synthetic mask-review checks; never reads production data."""
from pathlib import Path
import subprocess
import sys

if __name__ == '__main__':
    root=Path(__file__).resolve().parents[2]
    raise SystemExit(subprocess.call([sys.executable,'-m','unittest','discover','-s','tests','-p','test_review.py'],cwd=root))
