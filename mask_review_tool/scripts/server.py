"""Local mask review server. Source images and masks are read-only."""
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = 'mask_review_tool.scripts'
from loom_tools.config import add_arguments, resolve, print_config
from loom_tools.data import grouped_images
from ..state import signature, load_reviews
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from PIL import Image, ImageDraw, ImageChops
import argparse
import csv
import io
import json
import math
import threading
from collections import deque
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / 'data'
OUT = ROOT / 'outputs'
LOCK = threading.Lock()
STATUSES = {'unreviewed', 'ok', 'fix', 'hold'}


def validate_regions(regions, width, height):
    if not isinstance(regions, list) or len(regions) > 100:
        raise ValueError('領域数不正')
    for region in regions:
        if region.get('selection') not in {None, 'mask_intersection', 'mask_connected'}:
            raise ValueError('選択方式不正')
        if region['label'] not in {'weft', 'warp', 'overlap', 'unknown'}:
            raise ValueError('種別不正')
        if not isinstance(region.get('note', ''), str) or len(region.get('note', '')) > 10000:
            raise ValueError('メモ不正')
        points = region['points']
        if not isinstance(points, list) or not 3 <= len(points) <= 500:
            raise ValueError('頂点数不正')
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError('座標不正')
            x, y = point
            if not all(type(v) in (int, float) and math.isfinite(v) for v in point):
                raise ValueError('座標不正')
            if not 0 <= x <= width or not 0 <= y <= height:
                raise ValueError('座標範囲不正')
        area = abs(sum(points[i][0]*points[(i+1)%len(points)][1]-points[(i+1)%len(points)][0]*points[i][1] for i in range(len(points))))/2
        if area < 1:
            raise ValueError('面積不正')


def connected_selection(source, selection):
    """Select full 8-connected source components touched by selection."""
    width, height = source.size
    pixels, seeds = source.tobytes(), selection.tobytes()
    selected = bytearray(len(pixels))
    queue = deque()
    for i, (value, seed) in enumerate(zip(pixels, seeds)):
        if value and seed:
            selected[i] = 255
            queue.append(i)
    while queue:
        i = queue.popleft()
        x, y = i % width, i // width
        for yy in range(max(0,y-1), min(height,y+2)):
            for xx in range(max(0,x-1), min(width,x+2)):
                neighbor = yy * width + xx
                if pixels[neighbor] and not selected[neighbor]:
                    selected[neighbor] = 255
                    queue.append(neighbor)
    return Image.frombytes('L', source.size, bytes(selected))


def class_mask(mask_path, regions):
    """0=unassigned, 1=warp, 2=weft, 3=overlap, 4=unknown; only source value 1."""
    with Image.open(mask_path) as source:
        source = source.convert('L').point(lambda p: 255 if p == 1 else 0)
    layers = {label: Image.new('L', source.size) for label in ['warp','weft','overlap','unknown']}
    for region in regions:
        if region.get('selection') not in {'mask_intersection', 'mask_connected'}:
            continue  # Existing explanatory polygons remain reference ROIs.
        selection = Image.new('L', source.size)
        ImageDraw.Draw(selection).polygon([tuple(p) for p in region['points']], fill=255)
        layers[region['label']] = ImageChops.lighter(layers[region['label']], connected_selection(source, selection))
    result = Image.new('L', source.size)
    result.paste(1, mask=layers['warp'])
    result.paste(2, mask=layers['weft'])
    overlap = ImageChops.lighter(layers['overlap'], ImageChops.multiply(layers['warp'], layers['weft']))
    result.paste(3, mask=overlap)
    result.paste(4, mask=layers['unknown'])
    return result


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def inventory(raw_dir=None, mask_dir=None, output_dir=None):
    raw = grouped_images(raw_dir or DATA/'raw', {'.jpg','.jpeg'})
    masks = grouped_images(mask_dir or DATA/'masks', {'.png'})
    rows = []
    for key in sorted(raw, key=lambda k: (k.split('/')[0], int(k.split('/')[2]), k)):
        p = raw[key]
        with Image.open(p) as image:
            size = image.size
        row = dict(id=key, machine=key.split('/')[0], angle=key.split('/')[2], filename=p.name,
                   width=size[0], height=size[1], mask_pixels=None, ratio=None, issues=[])
        if key not in masks:
            row['issues'].append('マスクなし')
        else:
            with Image.open(masks[key]) as mask:
                if mask.size != size:
                    row['issues'].append('寸法不一致')
                if mask.mode != 'L':
                    row['issues'].append('想定外のマスク形式')
                else:
                    hist = mask.histogram()
                    if sum(hist[2:]):
                        row['issues'].append('0/1以外の値')
                    row['mask_pixels'] = hist[1]
                    row['ratio'] = hist[1] / (mask.width * mask.height)
                    if not hist[1]:
                        row['issues'].append('空マスク')
        rows.append(row)
    result = dict(items=rows, orphan_masks=sorted(masks.keys()-raw.keys()))
    target = Path(output_dir or OUT)
    target.mkdir(parents=True, exist_ok=True)
    atomic_json(target/'inventory.json', result)
    return result, raw, masks


class Handler(BaseHTTPRequestHandler):
    def reply(self, body, content_type='application/json; charset=utf-8', status=200):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            return self.get_response()
        except SourceChanged as error:
            return self.reply({'error': str(error)}, status=409)
        except OSError:
            return self.reply({'error': '画像を読めません'}, status=404)

    def get_response(self):
        url = urlsplit(self.path)
        if url.path == '/api/inventory':
            return self.reply(self.server.inventory)
        if url.path == '/api/reviews':
            with LOCK:
                return self.reply(self.server.reviews)
        if url.path in {'/api/labels.png', '/api/labels-overlay.png'}:
            key = parse_qs(url.query).get('id', [''])[0]
            if key not in self.server.masks:
                return self.reply({'error': 'マスクがありません'}, status=404)
            with LOCK:
                regions = self.server.reviews.get(key, {}).get('regions', [])
            assert_sources(self.server, key)
            labels = class_mask(self.server.masks[key], regions)
            if url.path == '/api/labels-overlay.png':
                overlay = Image.new('RGBA', labels.size)
                for value, color in [(1,(54,216,135,180)),(2,(57,170,255,180)),(3,(207,133,255,180)),(4,(255,216,77,180))]:
                    overlay.paste(color, mask=labels.point(lambda p: 255 if p == value else 0))
                labels = overlay
            buffer = io.BytesIO()
            labels.save(buffer, format='PNG')
            return self.reply(buffer.getvalue(), 'image/png')
        if url.path in {'/api/raw', '/api/mask'}:
            key = parse_qs(url.query).get('id', [''])[0]
            paths = self.server.raw if url.path == '/api/raw' else self.server.masks
            if key not in paths:
                return self.reply({'error': '画像がありません'}, status=404)
            assert_sources(self.server, key)
            if url.path == '/api/raw':
                return self.reply(paths[key].read_bytes(), 'image/jpeg')
            # Browser sees a transparent orange overlay, never a near-black 0/1 PNG.
            with Image.open(paths[key]) as mask:
                alpha = mask.convert('L').point(lambda p: 255 if p == 1 else 0)
                layer = Image.new('RGBA', mask.size, (255, 80, 25, 0))
                layer.putalpha(alpha)
                buffer = io.BytesIO()
                layer.save(buffer, format='PNG')
            return self.reply(buffer.getvalue(), 'image/png')
        if url.path in {'/api/export.json', '/api/export.csv'}:
            with LOCK:
                reviews = dict(self.server.reviews)
            rows = [dict(id=r['id'], machine=r['machine'], angle=r['angle'], filename=r['filename'],
                         status=reviews.get(r['id'], {}).get('status', 'unreviewed'),
                         note=reviews.get(r['id'], {}).get('note', ''),
                         regions=reviews.get(r['id'], {}).get('regions', []),
                         updated_at=reviews.get(r['id'], {}).get('updated_at', '')) for r in self.server.inventory['items']]
            if url.path.endswith('.json'):
                return self.reply(rows)
            stream = io.StringIO(newline='')
            for row in rows:
                row['regions'] = json.dumps(row['regions'], ensure_ascii=False)
            writer = csv.DictWriter(stream, fieldnames=['id','machine','angle','filename','status','note','regions','updated_at'])
            writer.writeheader()
            writer.writerows(rows)
            return self.reply(stream.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8')
        files = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
        if url.path in files:
            mime = {'/': 'text/html', '/app.js': 'text/javascript', '/style.css': 'text/css'}[url.path]
            return self.reply((ROOT/'viewer'/files[url.path]).read_bytes(), mime+'; charset=utf-8')
        self.reply({'error': 'Not found'}, status=404)

    def do_POST(self):
        if self.path != '/api/reviews':
            return self.reply({'error': 'Not found'}, status=404)
        # Reject cross-origin writes; this server is intended for loopback use.
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            return self.reply({'error': 'Origin rejected'}, status=403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                raise ValueError('サイズ不正')
            value = json.loads(self.rfile.read(length))
            key, status, note = value['id'], value['status'], value.get('note', '')
            if key not in self.server.raw or status not in STATUSES or not isinstance(note, str) or len(note) > 10000:
                raise ValueError('入力不正')
            assert_sources(self.server, key)
            record = dict(status=status, note=note, updated_at=datetime.now(timezone.utc).isoformat())
            with Image.open(self.server.raw[key]) as image:
                width, height = image.size
            regions = value.get('regions')
            if regions is not None:
                validate_regions(regions, width, height)
                record['regions'] = regions
            with LOCK:
                if regions is None:
                    record['regions'] = self.server.reviews.get(key, {}).get('regions', [])
                updated = dict(self.server.reviews)
                updated[key] = record
                atomic_json(self.server.output/'reviews.json', updated)
                self.server.reviews = updated
            self.reply(record)
        except SourceChanged as error:
            self.reply({'error': str(error)}, status=409)
        except (ValueError, KeyError, TypeError):
            self.reply({'error': '確認結果の形式が不正です'}, status=400)
        except OSError:
            self.reply({'error': '保存に失敗しました'}, status=500)


class SourceChanged(Exception):
    pass


def assert_sources(server, key):
    if signature(server.raw, server.masks, key) != server.fingerprints[key]:
        raise SourceChanged('入力画像またはマスクが変更されました。サーバーを再起動して再確認してください。')


class ReviewServer(ThreadingHTTPServer):
    allow_reuse_address = False


def make_server(port=8765, raw_dir=None, mask_dir=None, output_dir=None):
    output=Path(output_dir or OUT).resolve();output.mkdir(parents=True,exist_ok=True)
    listing,raw,masks=inventory(raw_dir,mask_dir,output)
    fingerprints={key:signature(raw,masks,key) for key in raw}
    reviews,warnings=load_reviews(output,fingerprints)
    listing['warnings']=warnings
    server=ReviewServer(('127.0.0.1',port),Handler)
    server.inventory,server.raw,server.masks=listing,raw,masks
    server.output,server.reviews,server.fingerprints=output,reviews,fingerprints
    return server


def main():
    parser=argparse.ArgumentParser()
    add_arguments(parser)
    parser.add_argument('--inventory-only',action='store_true')
    args=parser.parse_args()
    try:
        config=resolve(args,'mask_review_tool');print_config(config)
        if args.inventory_only:
            listing,raw,masks=inventory(config.raw_dir,config.mask_dir,config.output_dir)
            print(f'Inventory: {len(raw)} raw images / {len(masks)} masks',flush=True)
            return
        server=make_server(config.port,config.raw_dir,config.mask_dir,config.output_dir)
    except (OSError,ValueError) as error:
        parser.exit(1,f'Cannot start mask review: {error}\nCheck --config, paths or --port.\n')
    print(f'Inventory: {len(server.raw)} raw images / {len(server.masks)} masks',flush=True)
    for warning in server.inventory['warnings']:print(warning,flush=True)
    print(f'Open http://127.0.0.1:{server.server_port}/  (Ctrl+C to stop)',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
