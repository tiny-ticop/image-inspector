"""Export only the committed, explicitly approved code/sample tree to a source ZIP."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TOP_FILES={'.gitignore','.gitattributes','README.md','setup.ps1','setup_tools.py','pyproject.toml','requirements.lock.txt','config.example.json'}
TOP_DIRS={'frame_viewer','mask_review_tool','loom_tools','tests','examples','scripts','.github','docs'}


def allowed(name):
    path=Path(name);parts=path.parts
    if not parts or path.is_absolute() or '..' in parts:return False
    if any(p in {'outputs','__pycache__','.venv','thread_classification','.git','release'} or p.startswith('.browser-') for p in parts):return False
    if path.name.startswith(('config.local','.env')) or path.suffix=='.pyc':return False
    if path.suffix.lower() in {'.npz','.npy','.joblib','.pkl','.csv'}:return False
    if path.name in {'reviews.json','inventory.json','source_fingerprints.json','result.json','manifest.json','points.json','notes.json'}:return False
    if len(parts)==1:return name in TOP_FILES
    if parts[0] not in TOP_DIRS:return False
    if path.suffix.lower() in {'.jpg','.jpeg','.png'}:return tuple(parts[:3])==('examples','demo','data')
    return True


def git(*arguments):
    return subprocess.check_output(['git','-c','safe.directory='+str(ROOT),*arguments],cwd=ROOT)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'release'/'loom-image-tools-source.zip');args=parser.parse_args()
    names=git('ls-tree','-r','--name-only','HEAD').decode('utf-8').splitlines()
    bad=[name for name in names if not allowed(name)]
    if bad:raise ValueError('Unexpected tracked files: '+repr(bad))
    content=git('archive','--format=zip','HEAD');target=args.output.resolve();target.parent.mkdir(parents=True,exist_ok=True)
    manifest={}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for item in archive.infolist():
            if not item.is_dir():
                data=archive.read(item)
                if len(data)>2*1024**2:raise ValueError('Unexpected large source/sample: '+item.filename)
                manifest[item.filename]=hashlib.sha256(data).hexdigest()
    target.write_bytes(content)
    with zipfile.ZipFile(target,'a',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('SOURCE_MANIFEST.json',json.dumps(dict(commit=git('rev-parse','HEAD').decode().strip(),files=manifest),indent=2))
    print(f'{target}\nFiles: {len(manifest)}\nBytes: {target.stat().st_size}')


if __name__=='__main__':main()
