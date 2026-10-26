"""Local viewer and analysis APIs; source images are read-only."""
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'frame_viewer'

import argparse
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from .variation import Manager
from .discovery import Discovery
from loom_tools.config import add_arguments, resolve, print_config

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / 'data' / 'raw'


def inventory(root=DATA):
    machines = []
    paths = {}
    if not root.is_dir():
        raise ValueError(f'Data folder not found: {root}')
    for machine in sorted(p for p in root.iterdir() if p.is_dir()):
        delay = machine / 'delay'
        angles = []
        for folder in sorted((p for p in delay.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: (int(p.name), p.name)) if delay.is_dir() else []:
            frames = []
            for path in sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {'.jpg', '.jpeg'}):
                resolved = path.resolve()
                if not resolved.is_relative_to(root.resolve()):
                    continue
                key = path.relative_to(root).as_posix()
                paths[key] = resolved
                frames.append({'id':key, 'filename':path.name, 'angle':int(folder.name)})
            angles.append({'name':folder.name, 'angle':int(folder.name), 'frames':frames})
        machines.append({'name':machine.name, 'angles':angles})
    return {'machines':machines, 'images':len(paths), 'conditions':sum(len(m['angles']) for m in machines)}, paths


class Handler(BaseHTTPRequestHandler):
    def reply(self, body, mime, status=200):
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-cache')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url=urlsplit(self.path)
        if url.path.startswith('/api/variation/'):
            return self.variation_get(url)
        if url.path.startswith('/api/discovery/'):
            return self.discovery_get(url)
        if url.path=='/api/inventory':
            return self.reply(json.dumps(self.server.listing,ensure_ascii=False).encode('utf-8'),'application/json; charset=utf-8')
        if url.path=='/api/image':
            key=parse_qs(url.query).get('id',[''])[0]
            path=self.server.paths.get(key)
            if path:
                try:
                    return self.reply(path.read_bytes(),'image/jpeg')
                except OSError:
                    return self.reply(b'Image could not be read','text/plain',404)
        assets={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/player.js':('player.js','text/javascript'),'/variation.js':('variation.js','text/javascript'),'/discovery.js':('discovery.js','text/javascript'),'/style.css':('style.css','text/css')}
        if url.path in assets:
            name,mime=assets[url.path]
            return self.reply((ROOT/'viewer'/name).read_bytes(),mime+'; charset=utf-8')
        self.reply(b'Not found','text/plain',404)

    def json_reply(self,value,status=200):
        self.reply(json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8'),'application/json; charset=utf-8',status)

    def do_POST(self):
        try:
            origin=self.headers.get('Origin')
            if origin and urlsplit(origin).netloc!=self.headers.get('Host'):return self.json_reply({'error':'Origin rejected'},403)
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=65536:raise ValueError('要求サイズが不正です')
            value=json.loads(self.rfile.read(length));manager=self.server.variation
            if self.path=='/api/discovery/submit':
                names=value.get('machines')
                if not isinstance(names,list) or not 1<=len(names)<=20 or any(not isinstance(name,str) or name not in {m['name'] for m in self.server.listing['machines']} for name in names):raise ValueError('機台指定が不正です')
                from .discovery import config
                s=config(value.get('settings'))
                return self.json_reply({'jobs':[self.server.discovery.submit(name,s,value.get('variation_settings')) for name in names]})
            if self.path=='/api/discovery/region':return self.json_reply(self.server.discovery.region(value['id'],value.get('index'),value.get('rectangle')))
            if self.path=='/api/discovery/notes':return self.json_reply(self.server.discovery.notes(value['id'],value['notes']))
            if self.path=='/api/variation/submit':
                groups=value.get('groups')
                if not isinstance(groups,list) or not 1<=len(groups)<=100:raise ValueError('解析対象が不正です')
                # Validate the entire batch before enqueuing any jobs.
                from .variation import settings
                config=settings(value.get('settings'))
                for group in groups:
                    if not isinstance(group,dict) or (group.get('machine'),str(group.get('angle'))) not in manager.groups:raise ValueError('機台・角度がありません')
                    if len(manager.groups[(group['machine'],str(group['angle']))])<3:raise ValueError('解析には各角度3枚以上必要です')
                return self.json_reply({'jobs':[manager.submit(g['machine'],str(g['angle']),config) for g in groups]})
            if self.path=='/api/variation/roi':return self.json_reply(manager.roi(value['id'],value['rectangle']))
            return self.json_reply({'error':'Not found'},404)
        except (ValueError,KeyError,TypeError) as error:self.json_reply({'error':str(error)},400)
        except OSError as error:self.json_reply({'error':str(error)},500)

    def variation_get(self,url):
        try:
            query=parse_qs(url.query);manager=self.server.variation
            if url.path=='/api/variation/jobs':
                if 'id' in query:return self.json_reply(manager.status(query['id'][0]))
                with manager.lock:return self.json_reply({'jobs':list(manager.jobs.values())})
            key=query.get('id',[''])[0]
            if url.path=='/api/variation/image':return self.reply(manager.image(key,query.get('feature',['classes'])[0],int(query.get('frame',['0'])[0])),'image/png')
            if url.path=='/api/variation/download':
                manager.status(key)
                name=query.get('name',[''])[0]
                allowed={'maps.npz','series.csv','transforms.csv','result.json','frames.npy'}
                token=query.get('roi',[''])[0]
                if token:
                    if len(token)!=16 or any(c not in '0123456789abcdef' for c in token) or name not in {'json','csv'}:raise ValueError('出力指定が不正です')
                    path=manager.output/key/'roi'/(token+'.'+name)
                else:
                    if name not in allowed:raise ValueError('出力指定が不正です')
                    path=manager.output/key/name
                return self.reply(path.read_bytes(),'application/octet-stream')
            self.json_reply({'error':'Not found'},404)
        except (ValueError,KeyError,TypeError) as error:self.json_reply({'error':str(error)},400)
        except OSError as error:self.json_reply({'error':str(error)},404)

    def discovery_get(self,url):
        try:
            query=parse_qs(url.query);manager=self.server.discovery;key=query.get('id',[''])[0]
            if url.path=='/api/discovery/jobs':
                if key:return self.json_reply(manager.status(key))
                with manager.lock:return self.json_reply({'jobs':list(manager.jobs.values())})
            if url.path=='/api/discovery/image':return self.reply(manager.image(key,query.get('angle',[None])[0],query.get('cluster',[None])[0]),'image/png')
            if url.path=='/api/discovery/thumbnail':return self.reply(manager.thumbnail(key,int(query.get('index',['-1'])[0]),int(query.get('angle',['-1'])[0])),'image/png')
            if url.path=='/api/discovery/notes':return self.json_reply(manager.notes(key))
            if url.path=='/api/discovery/points':
                manager.data(key)
                return self.reply((manager.output/key/'points.json').read_bytes(),'application/json; charset=utf-8')
            if url.path=='/api/discovery/download':
                manager.data(key);name=query.get('name',[''])[0]
                if name not in {'result.json','features.npz','regions.csv','observations.npz','notes.json'}:raise ValueError('出力指定が不正です')
                return self.reply((manager.output/key/name).read_bytes(),'application/octet-stream')
            self.json_reply({'error':'Not found'},404)
        except (ValueError,TypeError,KeyError) as error:self.json_reply({'error':str(error)},400)
        except OSError as error:self.json_reply({'error':str(error)},404)


class ViewerServer(ThreadingHTTPServer):
    # Avoid Windows allowing a second listener to bind the same address.
    allow_reuse_address = False

    def server_close(self):
        if hasattr(self,'variation'):self.variation.close()
        super().server_close()


def make_server(port=8769, root=DATA, output=None, output_dir=None):
    listing,paths=inventory(root)
    server=ViewerServer(('127.0.0.1',port),Handler)
    server.listing,server.paths=listing,paths
    base=Path(output_dir).resolve() if output_dir is not None else (Path(output).parent if output else ROOT/'outputs')
    server.variation=Manager(listing,paths,Path(output) if output is not None else base/'variation')
    server.discovery=Discovery(server.variation,base/'pattern_discovery')
    return server


def main():
    parser=argparse.ArgumentParser();add_arguments(parser);args=parser.parse_args()
    try:
        config=resolve(args,'frame_viewer');print_config(config)
        server=make_server(config.port,config.raw_dir,output_dir=config.output_dir)
    except (OSError,ValueError) as error:
        parser.exit(1,f'Cannot start viewer: {error}\nPort may be in use; try --port 8770.\n')
    print(f"Images: {server.listing['images']} / Conditions: {server.listing['conditions']}",flush=True)
    print(f'Open http://127.0.0.1:{server.server_port}/  (Ctrl+C to stop)',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':main()
