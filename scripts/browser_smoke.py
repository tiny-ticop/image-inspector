"""Run both browser tools against temporary synthetic data, never production images."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from loom_tools.demo import generate
from frame_viewer.server import make_server as frame_server
from mask_review_tool.scripts.server import make_server as review_server


def main():
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='loom browser ') as temp:
        sample=Path(temp)/'人工 sample';generate(sample);raw=sample/'data/raw';masks=sample/'data/masks'
        frame=frame_server(0,raw,output_dir=sample/'outputs/frame_viewer')
        review=review_server(0,raw,masks,sample/'outputs/mask_review_tool')
        try:
            for server in [frame,review]:threading.Thread(target=server.serve_forever,daemon=True).start()
            for machine in frame.listing['machines']:
                for angle in machine['angles']:frame.variation.submit(machine['name'],angle['name'])
            first=frame.listing['machines'][0]
            aligned=frame.variation.submit(first['name'],first['angles'][0]['name'],dict(aligned=True))['id']
            discovered=frame.discovery.submit(first['name'])['id']
            deadline=time.monotonic()+180
            while frame.discovery.status(discovered)['state'] not in {'complete','failed'}:
                if time.monotonic()>deadline:raise RuntimeError('Analysis preparation timed out')
                time.sleep(.1)
            for state in [frame.variation.status(aligned),frame.discovery.status(discovered)]:
                if state['state']!='complete':raise RuntimeError(str(state))
            env=dict(os.environ,VARIATION_TEST='1',DISCOVERY_TEST='1',REVIEW_URL=f'http://127.0.0.1:{review.server_port}/')
            node=shutil.which('node')
            if not node:raise RuntimeError('Node 22+ is needed for browser tests only')
            subprocess.run([node,str(root/'frame_viewer/tests/test_browser.cjs'),f'http://127.0.0.1:{frame.server_port}/'],env=env,check=True,timeout=180)
        finally:
            for server in [frame,review]:server.shutdown();server.server_close()


if __name__=='__main__':main()
