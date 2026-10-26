"""Precompute machine-local discovery. Uses the viewer's shared sequential queue."""
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'frame_viewer'

import argparse
import json
import time
from .server import make_server
from .discovery import DEFAULTS
from loom_tools.config import add_arguments,resolve,print_config


def main():
    parser=argparse.ArgumentParser();add_arguments(parser);parser.add_argument('--machine');parser.add_argument('--min-cluster-size',type=int,default=40);parser.add_argument('--bootstraps',type=int,default=10);args=parser.parse_args()
    runtime=resolve(args,'frame_viewer');print_config(runtime)
    server=make_server(0,runtime.raw_dir,output_dir=runtime.output_dir)
    try:
        names=[args.machine] if args.machine else [m['name'] for m in server.listing['machines']]
        keys=[server.discovery.submit(name,{**DEFAULTS,'min_cluster_size':args.min_cluster_size,'bootstraps':args.bootstraps})['id'] for name in names]
        previous={}
        for key in keys:
            while True:
                job=server.discovery.status(key);stage=(job['state'],job['message'])
                if previous.get(key)!=stage:
                    print(json.dumps({k:job[k] for k in ['id','machine','state','progress','message']},ensure_ascii=False),flush=True);previous[key]=stage
                if job['state'] in {'complete','failed'}:break
                time.sleep(1)
        failed=[]
        for key in keys:
            job=server.discovery.status(key)
            if job['state']=='failed':failed.append(job)
            else:
                result=job['result'];print(json.dumps(dict(machine=job['machine'],regions=result['region_count'],clusters=len([c for c in result['clusters'] if c['label']>=0]),unclassified=result['unclassified_fraction'],seconds=result['elapsed_seconds'])),flush=True)
        if failed:raise SystemExit(json.dumps(failed,ensure_ascii=False))
    finally:server.server_close()


if __name__=='__main__':main()
