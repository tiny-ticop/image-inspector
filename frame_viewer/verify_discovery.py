"""Validate every machine result without treating clusters as semantic ground truth."""
import hashlib
import json
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'frame_viewer'

from pathlib import Path
import cv2
import numpy as np
from .server import ROOT
from .discovery import palette,DEFAULTS,VERSION
from .variation import csv_bytes
from loom_tools.config import add_arguments,resolve
import argparse


def main():
    parser=argparse.ArgumentParser();add_arguments(parser);runtime=resolve(parser.parse_args(),'frame_viewer')
    output=runtime.output_dir/'pattern_discovery';rows=[];contacts=[]
    for path in sorted(output.glob('*/result.json')):
        meta=json.loads(path.read_text(encoding='utf-8'))
        if meta['settings']!=DEFAULTS:continue
        spec={key:meta[key] for key in ['version','machine','settings','variation_settings','angle_jobs','angles']}
        assert hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:24]==path.parent.name
        assert meta['version']==VERSION and len(meta['bootstrap'])==10
        assert len(meta['angles'])>=3 and meta['angles']==sorted(meta['angles'])
        with np.load(path.parent/'features.npz') as f:data={name:f[name] for name in f.files}
        n=meta['region_count'];assert len(data['centers'])==len(data['labels'])==len(data['strength'])==n
        assert np.isfinite(data['reduced']).all() and np.isfinite(data['strength']).all()
        assert np.all((data['strength']>=0)&(data['strength']<=1))
        assert data['curves'].shape==(n,len(meta['angles']),6) and np.isfinite(data['curves']).all()
        assert sum(c['regions'] for c in meta['clusters'])==n
        assert abs(meta['unclassified_fraction']-float(np.mean(data['labels']<0)))<1e-8
        assert sum(c['area_pixels'] for c in meta['clusters'])==n*meta['settings']['stride']**2
        assert np.all(data['valid'][data['centers'][:,1],data['centers'][:,0]])
        assert all(0<=r['common_coverage']<=1 for r in meta['bootstrap'])
        for c in meta['clusters']:
            assert len(c['representatives'])==min(5,c['regions'])
            assert all(data['labels'][i]==c['label'] for i in c['representatives'])
            if c['label']>=0:assert 0<=c['stability_jaccard']<=1
        curves=data['curves'];inside=data['within'];outside=data['between']
        assigned=[c for c in meta['clusters'] if c['label']>=0]
        rows.append(dict(machine=meta['machine'],id=path.parent.name,angles=len(meta['angles']),regions=n,clusters=len(assigned),unclassified_percent=round(meta['unclassified_fraction']*100,2),seconds=meta['elapsed_seconds'],pca_dimensions=meta['pca_dimensions'],pca_explained=meta['pca_explained'],mean_matched_jaccard=float(np.mean([c['stability_jaccard'] for c in assigned])) if assigned else None,background_shift_suspected=any(r['suspected_shift'] for r in meta['background_diagnostics'])))
        base=cv2.cvtColor(data['medians'][len(meta['angles'])//2],cv2.COLOR_GRAY2BGR);layer=base.copy();r=meta['settings']['stride']//2
        colors={label:palette(int(label))[::-1] for label in set(data['labels'])}
        for (x,y),label in zip(data['centers'],data['labels']):layer[y-r:y+r,x-r:x+r]=colors[label]
        combined=cv2.addWeighted(base,.4,layer,.6,0)
        contact=np.concatenate([cv2.resize(a,(500,325)) for a in [base,combined]],axis=1)
        cv2.putText(contact,meta['machine']+f' clusters={len(assigned)} noise={meta["unclassified_fraction"]:.1%}',(8,20),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,255,255),1,cv2.LINE_AA);contacts.append(contact)
    from .server import inventory
    listing,_=inventory(runtime.raw_dir)
    expected={m['name'] for m in listing['machines'] if len(m['angles'])>=3 and all(len(a['frames'])>=3 for a in m['angles'])}
    assert {r['machine'] for r in rows}==expected and rows
    (output/'summary.csv').write_bytes(csv_bytes(rows));(output/'verification.json').write_text(json.dumps(dict(status='passed',machines=len(rows),rows=rows),ensure_ascii=False,indent=2),encoding='utf-8')
    cv2.imwrite(str(output/'overview.jpg'),np.concatenate(contacts,axis=0))
    print(json.dumps(rows,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
