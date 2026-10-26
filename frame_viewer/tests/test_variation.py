import sys
import tempfile
import unittest
import time
import threading
import json
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from pathlib import Path
import numpy as np
import cv2
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from frame_viewer.variation import compute,settings,classify,Manager
from frame_viewer.server import inventory,make_server


class VariationTests(unittest.TestCase):
    def test_http_analysis_and_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'raw';folder=root/'test'/'delay'/'80';folder.mkdir(parents=True)
            for i in range(3):cv2.imwrite(str(folder/f'{i}.jpg'),np.full((32,40),90+i*20,np.uint8))
            server=make_server(0,root,Path(directory)/'out');threading.Thread(target=server.serve_forever,daemon=True).start()
            base=f'http://127.0.0.1:{server.server_port}'
            def post(route,value,origin=None):
                headers={'Content-Type':'application/json'}
                if origin:headers['Origin']=origin
                with urlopen(Request(base+route,data=json.dumps(value).encode(),headers=headers)) as response:return json.load(response)
            try:
                result=post('/api/variation/submit',dict(groups=[dict(machine='test',angle='80')],settings=dict(top=2,border=2,window=3,sigma=2)))
                key=result['jobs'][0]['id']
                for _ in range(100):
                    with urlopen(base+'/api/variation/jobs?id='+key) as response:job=json.load(response)
                    if job['state'] in {'complete','failed'}:break
                    time.sleep(.03)
                self.assertEqual(job['state'],'complete')
                roi=post('/api/variation/roi',dict(id=key,rectangle=[3,3,20,20]))
                with urlopen(base+f'/api/variation/download?id={key}&roi={roi["export_id"]}&name=csv') as response:self.assertIn(b'absolute_deviation',response.read())
                with urlopen(base+f'/api/variation/image?id={key}&feature=excluded') as response:self.assertEqual(response.read()[:8],b'\x89PNG\r\n\x1a\n')
                with self.assertRaises(HTTPError) as e:post('/api/variation/roi',dict(id=key,rectangle=[-1,0,4,4]))
                self.assertEqual(e.exception.code,400)
                with self.assertRaises(HTTPError) as e:post('/api/variation/submit',dict(groups=[]),origin='http://example.com')
                self.assertEqual(e.exception.code,403)
            finally:server.shutdown();server.server_close()

    def test_rules_and_boundaries(self):
        s=settings();valid=np.ones((1,7),bool);low=np.array([[0,20,1,1,1,10,1.]])
        high=np.array([[0,1,20,20,20,10,20.]])
        fl=np.array([[0,.2,0,0,0,.5,0]])
        fh=np.array([[0,0,.2,.3,.5,.5,.1]])
        valid[0,6]=False
        np.testing.assert_array_equal(classify(low,high,fl,fh,valid,s),[[1,2,3,4,5,6,0]])

    def test_order_brightness_and_structure(self):
        s=settings(dict(top=0,border=2,window=3,sigma=4))
        stack=np.full((10,48,64),100,np.uint8)
        _,maps,_,_=compute(stack,s)
        self.assertTrue(np.all(maps['classes'][maps['valid']]==1))
        stack[:2]=150
        _,bright,_,_=compute(stack,s)
        self.assertTrue(np.all(bright['classes'][bright['valid']]==2))
        stack=np.full((10,48,64),100,np.uint8)
        stack[:2,16:32,30:32]=230
        _,a,_,_=compute(stack,s);_,b,_,_=compute(stack[[8,2,1,6,9,4,3,0,7,5]],s)
        for key in a:np.testing.assert_allclose(a[key],b[key],atol=1e-5,err_msg=key)
        self.assertTrue(np.any(a['classes']==3))
        self.assertEqual(float(a['high_frequency'].max()),np.float32(.2))
        self.assertTrue(np.all(a['classes'][~a['valid']]==0))
        self.assertTrue(np.all(a['std']>=a['mad']*.1))

    def test_alignment_and_failures(self):
        rng=np.random.default_rng(42);base=cv2.GaussianBlur(rng.integers(0,256,(96,128),np.uint8),(0,0),1)
        frames=np.stack([cv2.warpAffine(base,np.array([[1,0,x],[0,1,y]],np.float32),(128,96)) for x,y in [(0,0),(1,0),(-1,0),(0,1),(0,-1)]])
        s=settings(dict(top=4,border=6,aligned=True,window=3,sigma=4))
        _,maps,_,transforms=compute(frames,s)
        self.assertEqual(len(transforms),5)
        before=np.median([r['before'] for r in transforms]);after=np.median([r['after'] for r in transforms]);self.assertLess(after,before)
        with self.assertRaises(ValueError):compute(np.zeros((5,96,128),np.uint8),s)
        with self.assertRaises(ValueError):compute(frames[:2],s)
        for value in [dict(window=2),dict(rare=.8,frequent=.5),dict(threshold=float('nan'))]:
            with self.assertRaises(ValueError):settings(value)

    def test_jobs_roi_cache_and_input_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'raw';folder=root/'test'/'delay'/'80';folder.mkdir(parents=True)
            for i in range(4):cv2.imwrite(str(folder/f'{i}.jpg'),np.full((32,40),80+i*10,np.uint8))
            listing,paths=inventory(root);output=Path(directory)/'out';manager=Manager(listing,paths,output)
            try:
                config=dict(top=2,border=2,window=3,sigma=2)
                job=manager.submit('test','80',config);key=job['id']
                for _ in range(200):
                    if manager.status(key)['state'] in {'complete','failed'}:break
                    time.sleep(.03)
                self.assertEqual(manager.status(key)['state'],'complete',manager.status(key))
                self.assertEqual(manager.submit('test','80',config)['id'],key)
                self.assertEqual(manager.submit('test','80',{**config,'threshold':10,'sigma':2.0})['id'],key)
                roi=manager.roi(key,[2,2,20,20]);self.assertEqual(roi['valid_pixels'],18*18);self.assertEqual(len(roi['series']),4)
                with self.assertRaises(ValueError):manager.roi(key,[0,0,1,1])
                with self.assertRaises(ValueError):manager.roi(key,[-1,0,10,10])
                self.assertTrue((output/key/'roi'/(roi['export_id']+'.csv')).exists())
                self.assertEqual(manager.image(key,'classes')[:8],b'\x89PNG\r\n\x1a\n')
                cv2.imwrite(str(folder/'0.jpg'),np.zeros((32,40),np.uint8))
                self.assertNotEqual(manager.submit('test','80',config)['id'],key)
            finally:manager.close()


if __name__=='__main__':unittest.main()
