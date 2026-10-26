from pathlib import Path
import tempfile
import unittest
import threading
import json
import shutil
from urllib.request import urlopen,Request
from urllib.error import HTTPError
from PIL import Image
from loom_tools.demo import generate
from mask_review_tool.scripts.server import make_server,class_mask


class ReviewTests(unittest.TestCase):
    def test_content_binding_move_change_and_api(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);generate(root/'sample');raw=root/'sample/data/raw';masks=root/'sample/data/masks';output=root/'results'
            server=make_server(0,raw,masks,output);threading.Thread(target=server.serve_forever,daemon=True).start()
            base=f'http://127.0.0.1:{server.server_port}';key=next(iter(server.raw))
            record=dict(id=key,status='ok',note='確認済み',regions=[dict(label='weft',points=[[65,115],[130,115],[130,145],[65,145]],selection='mask_connected',note='reference')])
            def save(value):
                with urlopen(Request(base+'/api/reviews',data=json.dumps(value).encode(),headers={'Content-Type':'application/json'})) as r:return json.load(r)
            try:
                self.assertEqual(len(server.raw),24)
                self.assertEqual(save(record)['note'],'確認済み')
                for url in ['/','/app.js','/style.css','/api/inventory','/api/export.csv','/api/export.json','/api/labels.png?id='+key]:
                    with urlopen(base+url) as response:self.assertEqual(response.status,200)
                with urlopen(base+'/api/export.json') as response:self.assertEqual(len(json.load(response)),24)
                # A changed image must not accept annotations before restart.
                changed=server.raw[key];image=Image.open(changed).convert('RGB');image.putpixel((100,100),(255,0,0));image.save(changed)
                with self.assertRaises(HTTPError) as error:save(record)
                self.assertEqual(error.exception.code,409)
            finally:server.shutdown();server.server_close()
            changed_server=make_server(0,raw,masks,output)
            try:
                self.assertNotIn(key,changed_server.reviews)
                self.assertTrue(list(output.glob('reviews.quarantine.*.json')))
                changed_server.reviews[key]=record
            finally:changed_server.server_close()
            # Unchanged data may be copied to another drive/path without losing bindings.
            record_path=output/'reviews.json';record_path.write_text(json.dumps({key:record}),encoding='utf-8')
            shutil.copytree(root/'sample/data',root/'moved data')
            moved=make_server(0,root/'moved data/raw',root/'moved data/masks',output)
            try:self.assertEqual(moved.reviews[key]['note'],'確認済み')
            finally:moved.server_close()

    def test_legacy_backup_and_connected_classification(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);generate(root/'sample');output=root/'results';output.mkdir()
            key='demo_A/delay/95/frame_000'
            original={key:dict(status='ok',note='old',regions=[])}
            (output/'reviews.json').write_text(json.dumps(original),encoding='utf-8')
            server=make_server(0,root/'sample/data/raw',root/'sample/data/masks',output)
            try:
                self.assertEqual(server.reviews,original)
                backup=next(output.glob('reviews.backup.*.json'))
                self.assertEqual(json.loads(backup.read_text()),original)
                self.assertTrue(server.inventory['warnings'])
            finally:server.server_close()
            mask=Image.new('L',(20,20));mask.putpixel((3,3),1);mask.putpixel((4,4),1);mask.putpixel((5,5),1);mask.putpixel((12,12),1);path=root/'mask.png';mask.save(path)
            points=[[2,2],[3,2],[3,3],[2,3]]
            regions=[dict(label='weft',points=points,selection='mask_connected')]
            labels=class_mask(path,regions);self.assertEqual(labels.getpixel((5,5)),2);self.assertEqual(labels.getpixel((12,12)),0);self.assertEqual(labels.getpixel((2,2)),0)
            regions.append(dict(label='warp',points=points,selection='mask_connected'))
            self.assertEqual(class_mask(path,regions).getpixel((5,5)),3)
            regions.append(dict(label='unknown',points=points,selection='mask_connected'))
            self.assertEqual(class_mask(path,regions).getpixel((5,5)),4)


if __name__=='__main__':unittest.main()
