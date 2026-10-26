"""Verify all completed variation outputs and create a representative contact sheet."""
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'frame_viewer'

from pathlib import Path
import hashlib
import json
import cv2
import numpy as np
from .server import ROOT,DATA
from .variation import classify,PALETTE
from loom_tools.config import add_arguments,resolve
import argparse


def main():
    parser=argparse.ArgumentParser();add_arguments(parser);runtime=resolve(parser.parse_args(),'frame_viewer')
    output=runtime.output_dir/'variation';rows=[];examples={}
    for path in sorted(output.glob('*/result.json')):
        meta=json.loads(path.read_text(encoding='utf-8'))
        with np.load(path.parent/'maps.npz') as f:maps={name:f[name] for name in f.files}
        stack=np.load(path.parent/'frames.npy',mmap_mode='r');shape=(meta['height'],meta['width'])
        assert stack.shape==(meta['count'],*shape)
        assert all(array.shape==shape for array in maps.values())
        assert np.isfinite(stack).all() and all(np.isfinite(array).all() for array in maps.values())
        assert set(np.unique(maps['classes'])).issubset(set(range(7)))
        assert np.all(maps['classes'][~maps['valid']]==0)
        for name in ['low_frequency','high_frequency','orientation']:
            assert np.all((maps[name]>=0)&(maps[name]<=1))
        expected=classify(maps['low_mean'],maps['high_mean'],maps['low_frequency'],maps['high_frequency'],maps['valid'],meta['settings'])
        np.testing.assert_array_equal(expected,maps['classes'])
        assert int(maps['valid'].sum())==meta['valid_pixels']
        for frame in meta['inputs']:assert hashlib.sha256((runtime.raw_dir/frame['id']).read_bytes()).hexdigest()==frame['sha256']
        rows.append(dict(machine=meta['machine'],angle=meta['angle'],aligned=meta['settings']['aligned'],images=meta['count'],seconds=meta['elapsed_seconds'],python_peak_mb=meta['python_peak_mb']))
        if not meta['settings']['aligned'] and meta['machine'] not in examples:
            raw=cv2.imdecode(np.frombuffer((runtime.raw_dir/meta['frames'][0]['id']).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
            heat=cv2.applyColorMap(np.uint8(np.clip(maps['std']/30,0,1)*255),cv2.COLORMAP_TURBO)
            classes=cv2.cvtColor(PALETTE[maps['classes']],cv2.COLOR_RGB2BGR)
            alpha=maps['valid'].astype(np.float32)[...,None]*.65
            colored=np.uint8(raw*(1-alpha)+classes*alpha)
            contact=np.concatenate([cv2.resize(a,(500,325)) for a in [raw,heat,colored]],axis=1)
            cv2.putText(contact,meta['machine']+' / '+meta['angle'],(10,20),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,255,255),1,cv2.LINE_AA)
            examples[meta['machine']]=contact
        del stack,maps
    raw=list({(r['machine'],r['angle']):r for r in rows if not r['aligned']}.values());aligned=[r for r in rows if r['aligned']]
    from .server import inventory
    listing,_=inventory(runtime.raw_dir)
    expected={(m['name'],a['name']) for m in listing['machines'] for a in m['angles'] if len(a['frames'])>=3}
    assert {(r['machine'],r['angle']) for r in raw}==expected
    if not raw:raise ValueError('No completed raw analyses')
    result=dict(status='passed',raw_groups=len(raw),raw_images=sum(r['images'] for r in raw),aligned_groups=len(aligned),raw_seconds=dict(min=min(r['seconds'] for r in raw),max=max(r['seconds'] for r in raw),median=float(np.median([r['seconds'] for r in raw]))),python_peak_mb=max(r['python_peak_mb'] for r in rows),rows=rows)
    (output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    cv2.imwrite(str(output/'overview.jpg'),np.concatenate([examples[m] for m in sorted(examples)],axis=0))
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}),flush=True)


if __name__=='__main__':main()
