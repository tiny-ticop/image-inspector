import sys
import tempfile
import threading
import unittest
import json
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from frame_viewer import server
from loom_tools.demo import generate


class ServerTests(unittest.TestCase):
    def test_order_and_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for angle in ['104','95','100','96','97']:
                folder=root/'machine'/'delay'/angle;folder.mkdir(parents=True)
                if angle!='97':
                    for name in ['b.jpg','a.jpg']:(folder/name).write_bytes(b'example')
            listing,_=server.inventory(root)
            angles=listing['machines'][0]['angles']
            self.assertEqual([a['angle'] for a in angles],[95,96,97,100,104])
            self.assertEqual([f['filename'] for f in angles[0]['frames']],['a.jpg','b.jpg'])
            self.assertEqual(angles[2]['frames'],[])
            self.assertEqual(server.inventory(Path(directory)/'machine')[0]['images'],0)

    def test_real_inventory_and_http(self):
        temp=self.enterContext(tempfile.TemporaryDirectory())
        sample=Path(temp)/"demo"
        generate(sample)
        raw=sample/"data"/"raw"
        listing,paths=server.inventory(raw)
        self.assertEqual((len(listing['machines']),listing['conditions'],listing['images']),(2,6,24))
        for machine in listing['machines']:
            angles=machine['angles']
            self.assertEqual([a['angle'] for a in angles],sorted(a['angle'] for a in angles))
            for angle in angles:
                names=[f['filename'] for f in angle['frames']]
                self.assertEqual(names,sorted(names))
        http=server.make_server(0,raw,output_dir=Path(temp)/'outputs')
        threading.Thread(target=http.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{http.server_port}'
        try:
            for route in ['/','/app.js','/player.js','/style.css','/api/inventory']:
                with urlopen(base+route) as response:self.assertEqual(response.status,200)
            with urlopen(base+'/api/inventory') as response:self.assertEqual(json.load(response)['images'],24)
            from urllib.parse import quote
            key=next(iter(paths))
            with urlopen(base+'/api/image?id='+quote(key)) as response:self.assertEqual(response.read(),paths[key].read_bytes())
            for route in ['/api/image?id=../../outside','/../server.py']:
                with self.assertRaises(HTTPError) as error:urlopen(base+route)
                self.assertEqual(error.exception.code,404)
            # Deleted/unreadable files fail with an explicit HTTP error.
            http.paths['missing']=Path(tempfile.gettempdir())/'frame-viewer-missing-file.jpg'
            with self.assertRaises(HTTPError) as error:urlopen(base+'/api/image?id=missing')
            self.assertEqual(error.exception.code,404)
            with self.assertRaises(OSError):server.make_server(http.server_port,raw,output_dir=Path(temp)/'outputs')
        finally:
            http.shutdown();http.server_close()


if __name__=='__main__':unittest.main()
