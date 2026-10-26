"""Order-independent, per-angle appearance variation; no motion/normality GT claims."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import threading
import time
import tracemalloc
import cv2
import numpy as np

VERSION = 1
DEFAULTS = dict(threshold=10., rare=.20, frequent=.50, dominance=2/3,
                window=9, sigma=12., top=60, border=8, aligned=False)
CLASSES = ['評価対象外','変動が小さい','広域明暗変動主体','少数画像の構造変化',
           '中程度の出現割合の構造変化','多くの画像にある構造変化','混合・判別保留']
PALETTE = np.array([[0,0,0],[120,140,150],[255,190,40],[255,70,90],
                    [175,100,255],[30,190,230],[170,170,70]],np.uint8)
SCALES = dict(std=30., mad=30., spread=60., low_mean=30., high_mean=30.,
              low_frequency=1., high_frequency=1., orientation=1., current_low=30., current_high=30.)


def settings(value=None):
    value=value or {}
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):raise ValueError('未知の設定です')
    out={**DEFAULTS,**value}
    for key in DEFAULTS:
        if key=='aligned':
            if type(out[key]) is not bool:raise ValueError('位置合わせ設定が不正です')
        elif type(out[key]) not in (int,float) or not np.isfinite(out[key]):raise ValueError('設定値が不正です')
    if not (0 < out['threshold'] <= 255 and 0 < out['rare'] < out['frequent'] <= 1 and .5 < out['dominance'] <= 1):raise ValueError('閾値・割合の大小関係が不正です')
    if out['window']!=int(out['window']) or not 1<=out['window']<=51 or int(out['window'])%2!=1:raise ValueError('小領域幅は1〜51の奇数です')
    if not .5<=out['sigma']<=30:raise ValueError('sigmaは0.5〜30です')
    for key in ['top','border']:
        if out[key]!=int(out[key]) or not 0<=out[key]<=500:raise ValueError('除外幅が不正です')
        out[key]=int(out[key])
    out['window']=int(out['window'])
    # JSON 10 and 10.0 must use the same persistent cache key.
    for key in ['threshold','rare','frequent','dominance','sigma']:out[key]=float(out[key])
    return out


def valid_area(shape,s):
    h,w=shape;v=np.ones((h,w),np.uint8)
    b=s['border']
    if b:v[:b]=0;v[-b:]=0;v[:,:b]=0;v[:,-b:]=0
    v[:s['top']]=0
    if v.sum()<16:raise ValueError('除外範囲が大きすぎます')
    return v.astype(bool)


def local_parts(frame,median,valid,s):
    weights=valid.astype(np.float32)
    residual=frame.astype(np.float32)-median
    gaussian=lambda a:cv2.GaussianBlur(a,(0,0),s['sigma'])
    low=gaussian(residual*weights)/np.maximum(gaussian(weights),1e-6)
    high=residual-low
    size=(s['window'],s['window'])
    support=cv2.boxFilter(weights,-1,size)
    box=lambda a:cv2.boxFilter(np.abs(a)*weights,-1,size)/np.maximum(support,1e-6)
    return box(low),box(high)


def classify(low,high,fl,fh,valid,s):
    ratio=low/np.maximum(low+high,1e-6)
    active=(fl>0)|(fh>0)
    labels=np.ones(valid.shape,np.uint8)
    labels[active]=6
    labels[active&(fl>0)&(ratio>=s['dominance'])]=2
    structure=active&(fh>0)&(ratio<=1-s['dominance'])
    labels[structure&(fh<=s['rare']+1e-7)]=3
    labels[structure&(fh>s['rare']+1e-7)&(fh<s['frequent']-1e-7)]=4
    labels[structure&(fh>=s['frequent']-1e-7)]=5
    labels[~valid]=0
    return labels


def align_stack(stack,valid,progress):
    reference=np.median(stack,axis=0).astype(np.float32)
    spread=np.percentile(stack,90,axis=0)-np.percentile(stack,10,axis=0)
    gradient=cv2.magnitude(cv2.Sobel(reference,cv2.CV_32F,1,0),cv2.Sobel(reference,cv2.CV_32F,0,1))
    # Use contiguous regions; sparse pixel masks destabilize ECC's statistics.
    spread=cv2.GaussianBlur(spread.astype(np.float32),(0,0),5)
    gradient=cv2.GaussianBlur(gradient,(0,0),3)
    stable=valid&(spread<=np.percentile(spread[valid],60))&(gradient>np.percentile(gradient[valid],20))
    stable=(cv2.morphologyEx(stable.astype(np.uint8),cv2.MORPH_CLOSE,np.ones((9,9),np.uint8))>0)&valid
    if stable.sum()<100:raise ValueError('位置合わせに使える安定構造が不足しています')
    target=cv2.GaussianBlur(reference,(0,0),2)/255
    hann=cv2.createHanningWindow((valid.shape[1],valid.shape[0]),cv2.CV_32F)
    aligned=[];common=valid.copy();transforms=[]
    h,w=valid.shape
    for i,frame in enumerate(stack):
        progress(.10+.20*(i+1)/len(stack),'全体位置合わせ')
        try:
            image=cv2.GaussianBlur(frame.astype(np.float32),(0,0),2)/255
            shift,response=cv2.phaseCorrelate(target.copy(),image.copy(),hann)
            initial=np.eye(2,3,dtype=np.float32)
            if response>.1 and np.hypot(*shift)<20:initial[:,2]=shift
            cc,warp=cv2.findTransformECC(target,cv2.GaussianBlur(frame.astype(np.float32),(0,0),2)/255,
                initial.copy(),cv2.MOTION_TRANSLATION,
                (cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,100,1e-5),stable.astype(np.uint8)*255,1)
        except cv2.error as error:raise ValueError(f'{i+1}枚目の位置合わせに失敗しました。原画像解析は利用できます') from error
        if not np.isfinite(warp).all() or np.hypot(*warp[:,2])>20 or cc<.5:raise ValueError(f'{i+1}枚目の位置合わせ品質が不足しています（移動20px超またはECC<0.5）')
        result=cv2.warpAffine(frame,warp,(w,h),flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP)
        # Do not accept a refinement worse than its starting estimate or identity.
        alternatives=[(np.eye(2,3,dtype=np.float32),frame),(initial,cv2.warpAffine(frame,initial,(w,h),flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP)),(warp,result)]
        warp,result=min(alternatives,key=lambda pair:float(np.abs(pair[1].astype(float)-reference)[stable].mean()))
        area=cv2.warpAffine(valid.astype(np.uint8),warp,(w,h),flags=cv2.INTER_NEAREST|cv2.WARP_INVERSE_MAP)>0
        area=cv2.erode(area.astype(np.uint8),np.ones((3,3),np.uint8))>0
        common&=area;aligned.append(result)
        before=float(np.abs(frame.astype(float)-reference)[stable].mean());after=float(np.abs(result.astype(float)-reference)[stable].mean())
        transforms.append(dict(frame=i,ecc=float(cc),dx=float(warp[0,2]),dy=float(warp[1,2]),before=before,after=after,warning='補正後の差分が増加' if after>before*1.05 else ''))
    if common.sum()<100:raise ValueError('位置合わせ後の共通有効範囲が不足しています')
    return np.stack(aligned),common,transforms


def compute(stack,s,progress=lambda *_:None):
    if len(stack)<3:raise ValueError('解析には同じ角度の画像が3枚以上必要です')
    if stack.ndim!=3:raise ValueError('画像寸法が一致していません')
    n,h,w=stack.shape;valid=valid_area((h,w),s);transforms=[]
    if s['aligned']:stack,valid,transforms=align_stack(stack,valid,progress)
    progress(.32,'中央値・ばらつき')
    median=np.median(stack,axis=0).astype(np.float32)
    maps=dict(median=median,valid=valid,std=stack.std(axis=0,dtype=np.float32),
              mad=np.median(np.abs(stack.astype(np.float32)-median),axis=0).astype(np.float32),
              spread=(np.percentile(stack,95,axis=0)-np.percentile(stack,5,axis=0)).astype(np.float32))
    low_sum=np.zeros((h,w),np.float64);high_sum=low_sum.copy();lc=np.zeros((h,w),np.uint16);hc=lc.copy()
    vx=np.zeros((h,w),np.float64);vy=vx.copy();weight=vx.copy();direction_count=lc.copy();series=[]
    direction_valid=cv2.erode(valid.astype(np.uint8),np.ones((5,5),np.uint8))>0
    for i,frame in enumerate(stack):
        low,high=local_parts(frame,median,valid,s);low_sum+=low;high_sum+=high
        lc+=low>s['threshold'];hc+=high>s['threshold']
        gray=frame.astype(np.float32)
        gx=cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3)/8;gy=cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3)/8
        blur=lambda a:cv2.GaussianBlur(a,(0,0),2)
        xx,yy,xy=blur(gx*gx),blur(gy*gy),blur(gx*gy)
        trace=xx+yy;mag=np.sqrt((xx-yy)**2+4*xy**2);coherence=mag/np.maximum(trace,1e-6)
        use=(coherence>=.2)&(trace>=4)&direction_valid
        weighted=np.where(use,coherence,0);vx+=weighted*(xx-yy)/np.maximum(mag,1e-6);vy+=weighted*2*xy/np.maximum(mag,1e-6);weight+=weighted;direction_count+=use
        series.append(dict(frame=i,low=float(low[valid].mean()),high=float(high[valid].mean()),absolute_deviation=float(np.abs(gray-median)[valid].mean())))
        progress(.35+.50*(i+1)/n,'小領域・方向特徴')
    maps.update(low_mean=(low_sum/n).astype(np.float32),high_mean=(high_sum/n).astype(np.float32),low_frequency=lc.astype(np.float32)/n,high_frequency=hc.astype(np.float32)/n)
    orientation=(1-np.sqrt(vx*vx+vy*vy)/np.maximum(weight,1e-6)).clip(0,1).astype(np.float32)
    orientation_valid=(direction_count>=max(2,int(np.ceil(n/2))))&valid
    maps.update(orientation=orientation,orientation_valid=orientation_valid,
                classes=classify(maps['low_mean'],maps['high_mean'],maps['low_frequency'],maps['high_frequency'],valid,s))
    for name,array in maps.items():
        if name not in {'median','valid','orientation_valid','classes'}:array[~valid]=0
    return stack,maps,series,transforms


def csv_bytes(rows):
    buffer=io.StringIO(newline='')
    if rows:
        writer=csv.DictWriter(buffer,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return buffer.getvalue().encode('utf-8-sig')


def png(array):
    ok,buffer=cv2.imencode('.png',array)
    if not ok:raise ValueError('PNG生成に失敗しました')
    return buffer.tobytes()


class Manager:
    def __init__(self,listing,paths,output):
        self.paths=paths;self.output=Path(output);self.jobs={};self.lock=threading.RLock()
        self.groups={(m['name'],a['name']):a['frames'] for m in listing['machines'] for a in m['angles']}
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='variation')
        self.cache=OrderedDict();self.cache_lock=threading.RLock()
        for complete in self.output.glob('*/result.json'):
            try:
                result=json.loads(complete.read_text(encoding='utf-8'))
                spec={name:result[name] for name in ['version','machine','angle','settings','inputs']}
                spec['settings']=settings(spec['settings'])
                expected=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:24]
                if complete.parent.name!=expected:continue
                group=self.groups.get((result['machine'],result['angle']),[])
                if result['version']!=VERSION or [f['id'] for f in group]!=[f['id'] for f in result['frames']]:continue
                if any(hashlib.sha256(self.paths[f['id']].read_bytes()).hexdigest()!=f['sha256'] for f in result['inputs']):continue
                key=complete.parent.name
                self.jobs[key]=dict(id=key,state='complete',progress=1,message='保存済み結果',machine=result['machine'],angle=result['angle'],settings=result['settings'],result=result)
            except (ValueError,KeyError,OSError):continue

    def submit(self,machine,angle,config=None):
        s=settings(config);frames=self.groups.get((machine,str(angle)))
        if frames is None:raise ValueError('機台・角度がありません')
        if len(frames)<3:raise ValueError('解析には同じ角度の画像が3枚以上必要です')
        inputs=[dict(id=f['id'],sha256=hashlib.sha256(self.paths[f['id']].read_bytes()).hexdigest()) for f in frames]
        spec=dict(version=VERSION,machine=machine,angle=str(angle),settings=s,inputs=inputs)
        key=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:24]
        with self.lock:
            if key in self.jobs and self.jobs[key]['state']!='failed':return dict(self.jobs[key])
            destination=self.output/key
            complete=destination/'result.json'
            if complete.exists():
                result=json.loads(complete.read_text(encoding='utf-8'));self.jobs[key]=dict(id=key,state='complete',progress=1,message='保存済み結果',machine=machine,angle=str(angle),settings=s,result=result)
            else:
                self.jobs[key]=dict(id=key,state='queued',progress=0,message='待機中',machine=machine,angle=str(angle),settings=s)
                self.pool.submit(self._run,key,spec,frames)
            return dict(self.jobs[key])

    def update(self,key,**values):
        with self.lock:self.jobs[key].update(values)

    def status(self,key):
        with self.lock:
            if key not in self.jobs:raise ValueError('解析IDがありません。解析を再要求してください')
            return dict(self.jobs[key])

    def _run(self,key,spec,frames):
        start=time.perf_counter();tracemalloc.start();peak=0
        try:
            self.update(key,state='running',message='画像読み込み',progress=.02)
            arrays=[]
            for f,expected in zip(frames,spec['inputs']):
                data=self.paths[f['id']].read_bytes()
                if hashlib.sha256(data).hexdigest()!=expected['sha256']:raise ValueError('画像が変更されました。再度解析してください')
                image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_GRAYSCALE)
                if image is None:raise ValueError('画像を読めません: '+f['id'])
                if arrays and image.shape!=arrays[0].shape:raise ValueError('画像寸法が一致していません: '+f['id'])
                arrays.append(image)
            stack=np.stack(arrays);del arrays
            stack,maps,series,transforms=compute(stack,spec['settings'],lambda p,m:self.update(key,progress=p,message=m))
            self.update(key,progress=.9,message='結果保存')
            destination=self.output/key;destination.mkdir(parents=True,exist_ok=True)
            np.save(destination/'frames.npy',stack)
            np.savez_compressed(destination/'maps.npz',**maps)
            for row,f in zip(series,frames):row['id']=f['id']
            (destination/'series.csv').write_bytes(csv_bytes(series));(destination/'transforms.csv').write_bytes(csv_bytes(transforms))
            counts=np.bincount(maps['classes'].ravel(),minlength=len(CLASSES))
            peak=tracemalloc.get_traced_memory()[1]
            result=dict(**spec,frames=frames,width=stack.shape[2],height=stack.shape[1],count=len(frames),
                classes=CLASSES,colors=PALETTE.tolist(),scales=SCALES,series=series,transforms=transforms,
                class_pixels=counts.tolist(),valid_pixels=int(maps['valid'].sum()),elapsed_seconds=round(time.perf_counter()-start,3),
                python_peak_mb=round(peak/1024**2,1),memory_note='Python/NumPy追跡メモリ。OpenCV内部等を含むプロセス全体の上限ではありません',
                completed_at=datetime.now(timezone.utc).isoformat(),numpy=np.__version__,opencv=cv2.__version__,
                interpretation='周期間の外観変動。正常・異常・物体種別や物理原因を断定しません。中央値は評価画像も含みます。')
            temporary=destination/'result.tmp';temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(destination/'result.json')
            self.update(key,state='complete',progress=1,message='完了',result=result)
        except Exception as error:
            self.update(key,state='failed',progress=0,message=str(error))
        finally:tracemalloc.stop()

    def data(self,key):
        job=self.status(key)
        if job['state']!='complete':raise ValueError('解析が完了していません')
        with self.cache_lock:
            if key in self.cache:self.cache.move_to_end(key);return self.cache[key]
            path=self.output/key
            with np.load(path/'maps.npz') as f:maps={name:f[name] for name in f.files}
            data=(job['result'],np.load(path/'frames.npy'),maps)
            self.cache[key]=data
            while len(self.cache)>5:self.cache.popitem(last=False)
            return data

    def image(self,key,feature,index=0):
        meta,frames,maps=self.data(key)
        if not 0<=index<len(frames):raise ValueError('画像番号が不正です')
        if feature not in {*SCALES,'classes','frame','excluded'}:raise ValueError('特徴名が不正です')
        frame_specific=feature in {'frame','current_low','current_high'}
        path=self.output/key/'previews'/f'{feature}_{index if frame_specific else 0:03}.png'
        if path.exists():return path.read_bytes()
        if feature=='frame':
            data=png(frames[index]);path.parent.mkdir(exist_ok=True);path.write_bytes(data);return data
        valid=maps['valid'].copy()
        if feature=='excluded':
            rgb=np.full((*valid.shape,3),[255,40,40],np.uint8);valid=~valid
        elif feature=='classes':rgb=PALETTE[maps['classes']]
        else:
            if feature in {'current_low','current_high'}:
                low,high=local_parts(frames[index],maps['median'],valid,meta['settings']);array=low if feature=='current_low' else high
            elif feature in SCALES:array=maps[feature]
            else:raise ValueError('特徴名が不正です')
            if feature=='orientation':valid&=maps['orientation_valid']
            normalized=np.clip(array/SCALES[feature],0,1)
            rgb=cv2.cvtColor(cv2.applyColorMap(np.round(normalized*255).astype(np.uint8),cv2.COLORMAP_TURBO),cv2.COLOR_BGR2RGB)
        rgba=np.dstack([rgb,np.where(valid,200,0).astype(np.uint8)])
        data=png(cv2.cvtColor(rgba,cv2.COLOR_RGBA2BGRA))
        path.parent.mkdir(exist_ok=True);path.write_bytes(data)
        return data

    def roi(self,key,rectangle):
        meta,frames,maps=self.data(key);h,w=maps['valid'].shape
        if not isinstance(rectangle,list) or len(rectangle)!=4 or any(type(v) is not int for v in rectangle):raise ValueError('ROIは整数座標4個です')
        x0,y0,x1,y1=rectangle
        if not (0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError('ROIが画像範囲外です')
        area=np.zeros((h,w),bool);area[y0:y1,x0:x1]=True;area&=maps['valid']
        count=int(area.sum())
        if not count:raise ValueError('ROIに有効画素がありません')
        summary={name:float(maps[name][area].mean()) for name in ['std','mad','spread','low_mean','high_mean','low_frequency','high_frequency']}
        ov=area&maps['orientation_valid'];summary['orientation']=float(maps['orientation'][ov].mean()) if ov.any() else None
        classes=np.bincount(maps['classes'][area],minlength=len(CLASSES));series=[]
        for i,frame in enumerate(frames):
            low,high=local_parts(frame,maps['median'],maps['valid'],meta['settings'])
            series.append(dict(frame=i,id=meta['frames'][i]['id'],low=float(low[area].mean()),high=float(high[area].mean()),absolute_deviation=float(np.abs(frame.astype(np.float32)-maps['median'])[area].mean())))
        result=dict(job_id=key,rectangle=rectangle,coordinates='aligned' if meta['settings']['aligned'] else 'raw',settings=meta['settings'],valid_pixels=count,summary=summary,class_pixels=classes.tolist(),class_fraction=(classes/count).tolist(),series=series)
        token=hashlib.sha256(json.dumps(rectangle).encode()).hexdigest()[:16]
        folder=self.output/key/'roi';folder.mkdir(exist_ok=True)
        (folder/(token+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        (folder/(token+'.csv')).write_bytes(csv_bytes(series))
        result['export_id']=token
        return result

    def close(self):
        self.pool.shutdown(wait=True)
        with self.cache_lock:self.cache.clear()
