"""Precompute all same-angle groups with the same engine used by the UI."""
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'frame_viewer'

import argparse
import csv
import json
import time
from pathlib import Path
from .server import inventory,DATA,ROOT
from .variation import Manager,settings
from loom_tools.config import add_arguments,resolve,print_config


def main():
    parser=argparse.ArgumentParser();add_arguments(parser);parser.add_argument('--aligned',action='store_true');parser.add_argument('--representatives',action='store_true');args=parser.parse_args()
    runtime=resolve(args,'frame_viewer');print_config(runtime)
    listing,paths=inventory(runtime.raw_dir);manager=Manager(listing,paths,runtime.output_dir/'variation')
    config=settings(dict(aligned=args.aligned));jobs=[]
    try:
        for machine in listing['machines']:
            groups=machine['angles'][:1] if args.representatives else machine['angles']
            for angle in groups:
                if len(angle['frames'])>=3:jobs.append(manager.submit(machine['name'],angle['name'],config)['id'])
        rows=[]
        for index,key in enumerate(jobs):
            while manager.status(key)['state'] not in {'complete','failed'}:time.sleep(.25)
            job=manager.status(key);result=job.get('result',{})
            row=dict(machine=job['machine'],angle=job['angle'],id=key,state=job['state'],message=job['message'],images=result.get('count'),elapsed_seconds=result.get('elapsed_seconds'),python_peak_mb=result.get('python_peak_mb'),valid_pixels=result.get('valid_pixels'))
            rows.append(row);print(f'{index+1}/{len(jobs)} '+json.dumps(row,ensure_ascii=False),flush=True)
        filename='batch_aligned.csv' if args.aligned else 'batch_raw.csv'
        if not rows:
            print('No angle groups with at least three images.');return
        with (manager.output/filename).open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        if any(r['state']=='failed' for r in rows):raise SystemExit('Some groups failed; inspect batch CSV')
    finally:manager.close()


if __name__=='__main__':main()
