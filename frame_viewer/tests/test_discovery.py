import sys
import unittest
import tempfile
import time
import threading
import json
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.error import HTTPError
import cv2
import numpy as np
from sklearn.metrics import adjusted_rand_score
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from frame_viewer.discovery import summarize,cluster,config,grid,agreement
from frame_viewer.server import make_server


class DiscoveryTests(unittest.TestCase):
    def test_known_patterns_unlabeled(self):
        rng=np.random.default_rng(42);n=160;observations=[];angles=[80,81,84,85]
        for ai,angle in enumerate(angles):
            z=np.zeros((n,20,10),np.float32)
            # Four populations: stable; phase dependent; cycle variable; phase-local variability.
            for population in range(4):
                ids=slice(population*40,(population+1)*40)
                z[ids,:,0]=100+rng.normal(0,.2,(40,20))
                z[ids,:,1]=10;z[ids,:,2]=5;z[ids,:,5]=0
                z[ids,:,3:5]=np.nan
                if population==1:z[ids,:,0]+=(angle-80)*10
                if population==2:z[ids,:,0]+=rng.normal(0,20,(40,20));z[ids,:,7]=20
                if population==3 and ai==2:z[ids,:,0]+=rng.normal(0,40,(40,20));z[ids,:,7]=30
            observations.append(z)
        blocks,curves,inside,outside=summarize(observations,angles,10)
        labels,prob,_,_=cluster(blocks,config(dict(min_cluster_size=15,min_samples=5)))
        self.assertGreater(adjusted_rand_score(np.repeat(np.arange(4),40),labels),.6)
        self.assertTrue(np.isfinite(prob).all())
        reordered=[z[:,::-1] for z in observations]
        other,*_=summarize(reordered,angles,10)
        for a,b in zip(blocks,other):np.testing.assert_allclose(a,b,atol=1e-5,equal_nan=True)
        self.assertGreater(float(outside[40:80].mean()),float(outside[:40].mean())+10)
        self.assertGreater(float(inside[80:120].mean()),float(inside[:40].mean())+2)
        self.assertEqual(curves.shape,(160,4,6))

    def test_uniform_missing_and_label_permutation(self):
        labels,prob,_,_=cluster([np.zeros((50,2)),np.full((50,2),np.nan),np.zeros((50,2))],config())
        np.testing.assert_array_equal(labels,np.zeros(50))
        self.assertTrue(np.isfinite(prob).all())
        left=np.array([0,0,1,1,-1]);right=np.array([4,4,2,2,-1]);score=agreement(left,right)
        self.assertEqual(score['ari'],1);self.assertEqual(score['cluster_jaccard'],{'0':1.,'1':1.})
        self.assertIsNone(agreement(np.full(5,-1),np.full(5,-1))['ari'])
        valid=np.ones((48,64),bool);valid[:8]=False;centers=grid(valid,16,8)
        self.assertTrue(np.all(centers[:,1]>=16))
        with self.assertRaises(ValueError):config(dict(stride=16,patch=8))

    def test_api_queue_restore_and_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'raw';rng=np.random.default_rng(42)
            for angle in [80,81,84]:
                folder=root/'machine'/'delay'/str(angle);folder.mkdir(parents=True)
                for i in range(4):
                    image=np.full((48,64),100,np.uint8);image[15:25,10+angle%5:20+angle%5]=140+i*10;image[28:40,35:50]=rng.integers(0,255,(12,15),np.uint8);cv2.imwrite(str(folder/f'{i}.jpg'),image)
            output=Path(directory)/'out'/'variation';server=make_server(0,root,output);threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
            def post(route,value):
                with urlopen(Request(base+route,data=json.dumps(value).encode(),headers={'Content-Type':'application/json'})) as response:return json.load(response)
            try:
                job=post('/api/discovery/submit',dict(machines=['machine'],settings=dict(min_cluster_size=5,min_samples=2,bootstraps=1),variation_settings=dict(top=2,border=2,window=3,sigma=2)))['jobs'][0];key=job['id']
                for _ in range(300):
                    state=server.discovery.status(key)
                    if state['state'] in {'complete','failed'}:break
                    time.sleep(.03)
                self.assertEqual(state['state'],'complete',state)
                self.assertEqual(state['result']['angles'],[80,81,84])
                self.assertEqual(len(state['result']['bootstrap']),1)
                region=post('/api/discovery/region',dict(id=key,index=0));self.assertEqual(len(region['curve']),3)
                roi=post('/api/discovery/region',dict(id=key,rectangle=[0,0,64,48]));self.assertGreater(len(roi['indices']),1)
                label=str(state['result']['clusters'][0]['label']);saved=post('/api/discovery/notes',dict(id=key,notes={label:'test description'}));self.assertEqual(saved[label],'test description')
                for route in [f'/api/discovery/image?id={key}',f'/api/discovery/image?id={key}&angle=80',f'/api/discovery/thumbnail?id={key}&index=0&angle=80']:
                    with urlopen(base+route) as response:self.assertEqual(response.read()[:8],b'\x89PNG\r\n\x1a\n')
                with self.assertRaises(HTTPError):post('/api/discovery/region',dict(id=key,index=-1))
                with self.assertRaises(HTTPError):post('/api/discovery/submit',dict(machines=['machine'],variation_settings=dict(aligned=True)))
            finally:server.shutdown();server.server_close()
            restored=make_server(0,root,output)
            try:self.assertEqual(restored.discovery.notes(key)[label],'test description')
            finally:restored.server_close()
            new_angle=root/'machine'/'delay'/'86';new_angle.mkdir()
            for i in range(3):cv2.imwrite(str(new_angle/f'{i}.jpg'),np.full((48,64),100,np.uint8))
            changed=make_server(0,root,output)
            try:self.assertNotIn(key,changed.discovery.jobs)
            finally:changed.server_close()


if __name__=='__main__':unittest.main()
