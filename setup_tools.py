"""Create a local Python environment. Never modifies system Python or PowerShell policy."""
from pathlib import Path
import argparse
import importlib.metadata
import struct
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check-only',action='store_true');args=parser.parse_args()
    if sys.version_info[:2]!=(3,12) or struct.calcsize('P')!=8:parser.exit(1,'Python 3.12 (64-bit) is required. Install it and rerun setup.\n')
    environment=ROOT/'.venv';python=environment/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    if not python.exists():
        if args.check_only:parser.exit(1,'No local .venv. Run setup first.\n')
        venv.EnvBuilder(with_pip=True).create(environment)
    check=subprocess.run([str(python),'-c',"import sys,struct; assert sys.version_info[:2]==(3,12) and struct.calcsize('P')==8"],capture_output=True)
    if check.returncode:parser.exit(1,'Existing .venv is incompatible. Use a separate checkout with Python 3.12.\n')
    if not args.check_only:
        subprocess.run([str(python),'-m','pip','install','-r',str(ROOT/'requirements.lock.txt')],check=True)
        subprocess.run([str(python),'-m','pip','install','--no-deps','-e',str(ROOT)],check=True)
    subprocess.run([str(python),'-m','pip','check'],check=True)
    subprocess.run([str(python),'-c','from frame_viewer.server import make_server; from mask_review_tool.scripts.server import make_server; print("Both tools imported successfully")'],check=True,cwd=ROOT)
    print('Ready. Demo config: examples/demo/config.json')
    print('Frame viewer: powershell -NoProfile -ExecutionPolicy Bypass -File frame_viewer/start.ps1 --config examples/demo/config.json')
    print('Mask review:  powershell -NoProfile -ExecutionPolicy Bypass -File mask_review_tool/start.ps1 --config examples/demo/config.json')


if __name__=='__main__':
    try:main()
    except (OSError,subprocess.CalledProcessError) as error:
        print('Setup failed: '+str(error)+'\nCheck Python, network/proxy access and rerun setup.',file=sys.stderr);sys.exit(1)
