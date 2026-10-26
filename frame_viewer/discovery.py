"""Machine-local unsupervised discovery of within-phase and across-phase appearance."""
import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'frame_viewer'

from pathlib import Path
from collections import OrderedDict
import hashlib
import json
import threading
import time
import cv2
import joblib
import numpy as np
import sklearn
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import PCA
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import adjusted_rand_score
from scipy.optimize import linear_sum_assignment
from .variation import settings as variation_settings,local_parts,png,csv_bytes

VERSION=1
DEFAULTS=dict(patch=16,stride=8,min_cluster_size=40,min_samples=10,bootstraps=10,seed=42)
OBSERVATIONS=['brightness','contrast','gradient','cos2_direction','sin2_direction','direction_coverage','low_residual','high_residual','absolute_residual','rms_residual']


def config(value=None):
    value=value or {}
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):raise ValueError('未知の発見設定です')
    out={**DEFAULTS,**value}
    if any(type(v) is not int for v in out.values()):raise ValueError('発見設定は整数です')
    if out['patch'] not in {8,16,32} or out['stride'] not in {4,8,16} or out['stride']>out['patch']:raise ValueError('小領域・間隔が不正です')
    if not 5<=out['min_cluster_size']<=500 or not 2<=out['min_samples']<=100 or not 1<=out['bootstraps']<=20 or not 0<=out['seed']<2**32:raise ValueError('クラスタ設定の範囲が不正です')
    return out


def grid(valid,patch,stride):
    h,w=valid.shape;r=patch//2
    xx,yy=np.meshgrid(np.arange(r,w-r+1,stride),np.arange(r,h-r+1,stride))
    centers=np.column_stack([xx.ravel(),yy.ravel()]).astype(np.int32)
    integral=cv2.integral(valid.astype(np.uint8))
    x,y=centers.T
    area=integral[y+r,x+r]-integral[y-r,x+r]-integral[y+r,x-r]+integral[y-r,x-r]
    return centers[area==patch*patch]


def observe(frame,median,valid,s,centers,patch):
    image=frame.astype(np.float32);x,y=centers.T
    mean=lambda a:cv2.boxFilter(a,cv2.CV_32F,(patch,patch))[y,x]
    mu=mean(image);contrast=np.sqrt(np.maximum(mean(image*image)-mu*mu,0))
    gx=cv2.Sobel(image,cv2.CV_32F,1,0)/8;gy=cv2.Sobel(image,cv2.CV_32F,0,1)/8
    xx,yy,xy=mean(gx*gx),mean(gy*gy),mean(gx*gy)
    energy=xx+yy;length=np.sqrt((xx-yy)**2+4*xy**2);coherence=length/np.maximum(energy,1e-6)
    direction=(energy>=4)&(coherence>=.2)
    c=np.where(direction,(xx-yy)/np.maximum(length,1e-6),np.nan)
    sin=np.where(direction,2*xy/np.maximum(length,1e-6),np.nan)
    low,high=local_parts(frame,median,valid,s)
    residual=image-median
    return np.column_stack([mu,contrast,mean(cv2.magnitude(gx,gy)),c,sin,direction.astype(float),mean(low),mean(high),mean(np.abs(residual)),np.sqrt(mean(residual*residual))]).astype(np.float32)


def summarize(observations,angles,threshold):
    """Each angle contributes once, regardless of its number of sampled images."""
    import warnings
    representatives=[];within=[];curves=[]
    for z in observations:  # points x frames x channels
        med=np.median(z[:,:,:3],axis=1)
        mad=np.median(np.abs(z[:,:,:3]-med[:,None,:]),axis=1)
        spread=np.percentile(z[:,:,:3],95,axis=1)-np.percentile(z[:,:,:3],5,axis=1)
        means=np.mean(z[:,:,6:10],axis=1)
        frequency=np.mean(z[:,:,6:8]>threshold,axis=1)
        coverage=np.mean(z[:,:,5],axis=1)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',RuntimeWarning)
            cosine=np.nanmean(z[:,:,3],axis=1);sine=np.nanmean(z[:,:,4],axis=1)
        representative=np.column_stack([med,cosine,sine,coverage])
        direction_dispersion=1-np.sqrt(np.nan_to_num(cosine)**2+np.nan_to_num(sine)**2).clip(0,1)
        direction_dispersion[coverage<.5]=np.nan
        within.append(np.column_stack([mad,spread,means,frequency,direction_dispersion,coverage]))
        representatives.append(representative)
        curves.append(np.column_stack([med[:,0],mad[:,0],means[:,0],means[:,1],means[:,2],coverage]))
    representative=np.stack(representatives,axis=1);within=np.stack(within,axis=1);curves=np.stack(curves,axis=1)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        phase_center=np.nanmedian(representative,axis=1,keepdims=True)
        amplitude=np.nanmax(representative,axis=1)-np.nanmin(representative,axis=1)
    centered=representative-phase_center
    differences=np.diff(representative,axis=1)/np.diff(np.asarray(angles))[None,:,None]
    phase=np.concatenate([centered.reshape(len(within),-1),differences.reshape(len(within),-1),amplitude],axis=1)
    # Compare representative brightness change with between-cycle brightness dispersion.
    inside=np.mean(within[:,:,:3],axis=(1,2));outside=np.std(representative[:,:,0],axis=1)
    ratio=outside/(inside+1)
    wbrightness=within[:,:,0]
    relation=np.column_stack([inside,outside,ratio,np.std(wbrightness,axis=1),np.max(wbrightness,axis=1),np.argmax(wbrightness,axis=1)/max(1,len(angles)-1),np.max(np.abs(np.diff(representative[:,:,0],axis=1)/np.diff(angles)[None,:]),axis=1)])
    return [within.reshape(len(within),-1),phase,relation],curves,inside,outside


def transform(blocks,seed):
    matrices=[];models=[]
    for block in blocks:
        finite=np.isfinite(block);missing=~finite
        clean=np.where(finite,block,np.nan)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',RuntimeWarning);fill=np.nanmedian(clean,axis=0)
        fill=np.nan_to_num(fill);clean=np.where(finite,block,fill)
        scaler=RobustScaler();scaler.fit(clean)
        # Protect nearly constant features from numerical amplification.
        scaler.scale_=np.maximum(scaler.scale_,1e-3);scaled=scaler.transform(clean)
        columns=np.flatnonzero(missing.any(axis=0))
        if len(columns):scaled=np.column_stack([scaled,missing[:,columns]*.25])
        scaled=np.clip(scaled,-20,20)/np.sqrt(scaled.shape[1]);matrices.append(scaled);models.append(dict(fill=fill,scaler=scaler,missing_columns=columns))
    matrix=np.column_stack(matrices).astype(np.float32)
    if np.max(np.ptp(matrix,axis=0))<1e-7:
        return np.zeros((len(matrix),1),np.float32),dict(blocks=models,pca=None,dimensions=1,explained=0.)
    pca=PCA(n_components=min(20,matrix.shape[1],len(matrix)-1),svd_solver='randomized',random_state=seed)
    reduced=pca.fit_transform(matrix)
    cumulative=np.cumsum(pca.explained_variance_ratio_);dimensions=min(len(cumulative),int(np.searchsorted(cumulative,.95))+1)
    return reduced[:,:dimensions],dict(blocks=models,pca=pca,dimensions=dimensions,explained=float(cumulative[dimensions-1]))


def cluster(blocks,s):
    reduced,preprocessing=transform(blocks,s['seed'])
    if not len(reduced):raise ValueError('有効な小領域がありません')
    if np.max(np.ptp(reduced,axis=0))<1e-7:
        labels=np.zeros(len(reduced),np.int32);probability=np.ones(len(reduced),np.float32);model=None
    elif len(reduced)<max(s['min_samples'],s['min_cluster_size']):
        labels=np.full(len(reduced),-1,np.int32);probability=np.zeros(len(reduced),np.float32);model=None
    else:
        model=HDBSCAN(min_cluster_size=s['min_cluster_size'],min_samples=s['min_samples'],allow_single_cluster=True,cluster_selection_method='eom',n_jobs=1,copy=True)
        labels=model.fit_predict(reduced).astype(np.int32);probability=np.nan_to_num(model.probabilities_,nan=0.).astype(np.float32)
    return labels,probability,reduced,dict(preprocessing=preprocessing,cluster=model)


def agreement(reference,other):
    left=sorted(set(reference)-{-1});right=sorted(set(other)-{-1});common=(reference>=0)&(other>=0)
    if not left or not right:return dict(ari=None,assigned_ari=None,common_coverage=float(common.mean()),cluster_jaccard={})
    overlaps=np.zeros((len(left),len(right)))
    for i,a in enumerate(left):
        for j,b in enumerate(right):
            aa=reference==a;bb=other==b;overlaps[i,j]=np.count_nonzero(aa&bb)/max(1,np.count_nonzero(aa|bb))
    rows,cols=linear_sum_assignment(-overlaps);matched={str(a):0. for a in left}
    for i,j in zip(rows,cols):matched[str(left[i])]=float(overlaps[i,j])
    return dict(ari=float(adjusted_rand_score(reference,other)),assigned_ari=float(adjusted_rand_score(reference[common],other[common])) if common.sum()>1 else None,common_coverage=float(common.mean()),cluster_jaccard=matched)


def palette(label):
    if label<0:return [145,145,145]
    hsv=np.uint8([[[int((label*.61803398875%1)*179),190,235]]])
    return cv2.cvtColor(hsv,cv2.COLOR_HSV2RGB)[0,0].tolist()


class Discovery:
    def __init__(self,variation,output):
        self.variation=variation;self.output=Path(output);self.jobs={};self.lock=threading.RLock();self.cache=OrderedDict();self.cache_lock=threading.RLock()
        for path in self.output.glob('*/result.json'):
            try:
                result=json.loads(path.read_text(encoding='utf-8'))
                if result['version']!=VERSION or any(job not in variation.jobs for job in result['angle_jobs']):continue
                current=sorted(int(angle) for machine,angle in variation.groups if machine==result['machine'])
                if current!=result['angles']:continue
                spec={name:result[name] for name in ['version','machine','settings','variation_settings','angle_jobs','angles']}
                if hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:24]!=path.parent.name:continue
                self.jobs[path.parent.name]=dict(id=path.parent.name,machine=result['machine'],state='complete',progress=1,message='保存済み結果',settings=result['settings'],variation_settings=result['variation_settings'],result=result)
            except (OSError,ValueError,KeyError):continue

    def submit(self,machine,value=None,variation_config=None):
        s=config(value);vs=variation_settings(variation_config)
        if vs['aligned']:raise ValueError('全角度の発見は原画像の共通座標で解析します。角度別の位置補正は利用できません')
        groups=sorted([(name,frames) for (m,name),frames in self.variation.groups.items() if m==machine],key=lambda a:int(a[0]))
        if len(groups)<3 or any(len(frames)<3 for _,frames in groups):raise ValueError('3角度以上、各角度3画像以上が必要です')
        prerequisites=[self.variation.submit(machine,angle,vs)['id'] for angle,_ in groups]
        spec=dict(version=VERSION,machine=machine,settings=s,variation_settings=vs,angle_jobs=prerequisites,angles=[int(a) for a,_ in groups])
        key=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:24]
        with self.lock:
            if key in self.jobs and self.jobs[key]['state']!='failed':return dict(self.jobs[key])
            self.jobs[key]=dict(id=key,machine=machine,state='queued',progress=0,message='角度別特徴の完了待ち',settings=s,variation_settings=vs)
            # All prerequisites are queued first on the same single worker.
            self.variation.pool.submit(self._run,key,spec)
            return dict(self.jobs[key])

    def status(self,key):
        with self.lock:
            if key not in self.jobs:raise ValueError('パターン発見IDがありません')
            return dict(self.jobs[key])

    def update(self,key,**value):
        with self.lock:self.jobs[key].update(value)

    def _run(self,key,spec):
        started=time.perf_counter();s=spec['settings'];vs=spec['variation_settings']
        try:
            self.update(key,state='running',progress=.01,message='共通座標・有効範囲を確認')
            metadata=[];valid=None;shape=None
            for job in spec['angle_jobs']:
                state=self.variation.status(job)
                if state['state']!='complete':raise ValueError('角度別解析に失敗しました: '+state['message'])
                metadata.append(state['result']);folder=self.variation.output/job
                with np.load(folder/'maps.npz') as f:
                    v=f['valid']
                    if shape is not None and v.shape!=shape:raise ValueError('角度間で画像寸法が一致しません')
                    shape=v.shape;valid=v.copy() if valid is None else valid&v
            centers=grid(valid,s['patch'],s['stride'])
            if len(centers)<10:raise ValueError('有効な小領域が不足しています')
            observations=[];medians=[];background=[]
            for ai,(job,meta) in enumerate(zip(spec['angle_jobs'],metadata)):
                folder=self.variation.output/job;frames=np.load(folder/'frames.npy')
                with np.load(folder/'maps.npz') as f:median=f['median']
                medians.append(np.uint8(np.clip(median,0,255)))
                angle=[]
                for i,frame in enumerate(frames):angle.append(observe(frame,median,valid,vs,centers,s['patch']))
                observations.append(np.stack(angle,axis=1))
                self.update(key,progress=.05+.25*(ai+1)/len(metadata),message=f'画像群から小領域特徴を抽出 {ai+1}/{len(metadata)}')
            # Background quality diagnostic only; never use shifts to warp away phase effects.
            stable_score=np.zeros(shape,np.float32)
            for job in spec['angle_jobs']:
                with np.load(self.variation.output/job/'maps.npz') as f:stable_score+=f['std']/len(spec['angle_jobs'])
            stable=valid&(stable_score<=np.percentile(stable_score[valid],30))
            template=medians[0].astype(np.float32)*stable;hann=cv2.createHanningWindow((shape[1],shape[0]),cv2.CV_32F)
            for angle,median in zip(spec['angles'],medians):
                shift,response=cv2.phaseCorrelate(template.copy(),median.astype(np.float32)*stable,hann)
                background.append(dict(angle=angle,dx=float(shift[0]),dy=float(shift[1]),response=float(response),suspected_shift=bool(response>.1 and np.hypot(*shift)>2)))
            blocks,curves,inside,outside=summarize(observations,spec['angles'],vs['threshold'])
            labels,strength,reduced,model=cluster(blocks,s)
            self.update(key,progress=.4,message='再抽出によるクラスタ安定性を検証')
            rng=np.random.default_rng(s['seed']);replicates=[]
            for trial in range(s['bootstraps']):
                sampled=[z[:,rng.integers(0,z.shape[1],size=z.shape[1]),:] for z in observations]
                sampled_blocks,*_=summarize(sampled,spec['angles'],vs['threshold'])
                other,_,_,_=cluster(sampled_blocks,s)
                score=agreement(labels,other);score.update(trial=trial,clusters=len(set(other)-{-1}),unclassified_fraction=float(np.mean(other<0)));replicates.append(score)
                self.update(key,progress=.4+.5*(trial+1)/s['bootstraps'],message=f'安定性検証 {trial+1}/{s["bootstraps"]}')
            folder=self.output/key;folder.mkdir(parents=True,exist_ok=True)
            np.savez_compressed(folder/'features.npz',centers=centers,labels=labels,strength=strength,reduced=reduced,within=inside,between=outside,curves=curves,medians=np.stack(medians),valid=valid,**{f'block_{i}':b for i,b in enumerate(blocks)})
            np.savez_compressed(folder/'observations.npz',**{f'angle_{i}':z for i,z in enumerate(observations)})
            joblib.dump(model,folder/'model.joblib')
            cluster_data=[]
            for label in sorted(set(labels)):
                members=np.flatnonzero(labels==label);feature_center=np.median(reduced[members],axis=0)
                order=members[np.argsort(np.linalg.norm(reduced[members]-feature_center,axis=1),kind='stable')]
                jaccard=[r['cluster_jaccard'].get(str(int(label)),0.) for r in replicates] if label>=0 else []
                cluster_data.append(dict(label=int(label),color=palette(int(label)),regions=len(members),area_pixels=int(len(members)*s['stride']**2),representatives=order[:5].tolist(),within=float(np.median(inside[members])),between=float(np.median(outside[members])),mean_strength=float(np.mean(strength[members])),stability_jaccard=float(np.mean(jaccard)) if jaccard else None,curve=np.nanmean(curves[members],axis=0).tolist()))
            points=dict(centers=centers.tolist(),labels=labels.tolist(),strength=strength.tolist(),within=inside.tolist(),between=outside.tolist())
            (folder/'points.json').write_text(json.dumps(points),encoding='utf-8')
            rows=[dict(region=i,x=int(x),y=int(y),cluster=int(labels[i]),membership_strength=float(strength[i]),within=float(inside[i]),between=float(outside[i])) for i,(x,y) in enumerate(centers)]
            (folder/'regions.csv').write_bytes(csv_bytes(rows))
            report=dict(**spec,clusters=cluster_data,region_count=len(centers),width=shape[1],height=shape[0],unclassified_fraction=float(np.mean(labels<0)),bootstrap=replicates,background_diagnostics=background,
                pca_dimensions=model['preprocessing']['dimensions'],pca_explained=model['preprocessing']['explained'],elapsed_seconds=round(time.perf_counter()-started,3),numpy=np.__version__,sklearn=sklearn.__version__,
                observation_names=OBSERVATIONS,curve_names=['brightness_median','brightness_MAD','low_residual','high_residual','absolute_residual','direction_coverage'],
                caveats=['固定場所のパターンで、物体追跡・意味分類ではありません','所属強度・安定性は正解確率ではありません','再抽出は画像ごとの小領域特徴を再標本化します。差分の参照中央値は固定し、その不確かさは含みません','重なった小領域は独立な統計標本ではありません','角度ごとの収録時刻差による状態差が混ざる可能性があります'])
            temporary=folder/'result.tmp';temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');temporary.replace(folder/'result.json')
            self.update(key,state='complete',progress=1,message='完了',result=report)
        except Exception as error:self.update(key,state='failed',progress=0,message=str(error))

    def data(self,key):
        state=self.status(key)
        if state['state']!='complete':raise ValueError('パターン発見が完了していません')
        with self.cache_lock:
            if key in self.cache:self.cache.move_to_end(key);return self.cache[key]
            with np.load(self.output/key/'features.npz') as f:data={name:f[name] for name in f.files}
            self.cache[key]=data
            while len(self.cache)>5:self.cache.popitem(last=False)
            return data

    def image(self,key,angle=None,selected=None):
        meta=self.status(key).get('result');data=self.data(key)
        if selected is not None and int(selected) not in set(data['labels']):raise ValueError('クラスタがありません')
        preview=self.output/key/'previews';preview.mkdir(exist_ok=True)
        path=preview/(f'median_{int(angle)}.png' if angle is not None else f'clusters_{"all" if selected is None else int(selected)}.png')
        if path.exists():return path.read_bytes()
        if angle is not None:
            if int(angle) not in meta['angles']:raise ValueError('角度がありません')
            content=png(data['medians'][meta['angles'].index(int(angle))]);path.write_bytes(content);return content
        h,w=data['valid'].shape;rgba=np.zeros((h,w,4),np.uint8);r=meta['settings']['stride']//2
        colors={label:palette(int(label)) for label in set(data['labels'])}
        for (x,y),label in zip(data['centers'],data['labels']):
            opacity=200 if selected is None or int(selected)==label else 20
            rgba[y-r:y+r,x-r:x+r,:3]=colors[label];rgba[y-r:y+r,x-r:x+r,3]=opacity
        content=png(cv2.cvtColor(rgba,cv2.COLOR_RGBA2BGRA));path.write_bytes(content);return content

    def region(self,key,index=None,rectangle=None):
        meta=self.status(key)['result'];data=self.data(key);centers=data['centers']
        if rectangle is not None:
            if not isinstance(rectangle,list) or len(rectangle)!=4 or any(type(v) is not int for v in rectangle):raise ValueError('ROIが不正です')
            x0,y0,x1,y1=rectangle
            if not 0<=x0<x1<=meta['width'] or not 0<=y0<y1<=meta['height']:raise ValueError('ROI範囲が不正です')
            indices=np.flatnonzero((centers[:,0]>=x0)&(centers[:,0]<x1)&(centers[:,1]>=y0)&(centers[:,1]<y1))
        else:
            if type(index) is not int or not 0<=index<len(centers):raise ValueError('領域番号が不正です')
            indices=np.array([index])
        if not len(indices):raise ValueError('ROIに解析領域の中心がありません')
        labels,counts=np.unique(data['labels'][indices],return_counts=True)
        curves=np.mean(data['curves'][indices],axis=0)
        result=dict(indices=indices.tolist(),angles=meta['angles'],curve=curves.tolist(),curve_names=meta['curve_names'],within=float(np.mean(data['within'][indices])),between=float(np.mean(data['between'][indices])),cluster_counts={str(int(label)):int(count) for label,count in zip(labels,counts)},centers=centers[indices].tolist())
        return result

    def thumbnail(self,key,index,angle):
        meta=self.status(key)['result'];data=self.data(key)
        if not 0<=index<len(data['centers']) or angle not in meta['angles']:raise ValueError('代表領域・角度が不正です')
        x,y=data['centers'][index];h,w=data['valid'].shape
        left,top=max(0,x-48),max(0,y-48);right,bottom=min(w,x+48),min(h,y+48)
        crop=data['medians'][meta['angles'].index(angle),top:bottom,left:right]
        crop=cv2.cvtColor(crop,cv2.COLOR_GRAY2BGR);r=meta['settings']['patch']//2
        cv2.rectangle(crop,(max(0,x-r-left),max(0,y-r-top)),(min(right-left-1,x+r-left),min(bottom-top-1,y+r-top)),(255,255,255),1)
        return png(cv2.resize(crop,(192,192),interpolation=cv2.INTER_NEAREST))

    def notes(self,key,value=None):
        self.status(key);path=self.output/key/'notes.json'
        with self.lock:
            if value is None:return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
            if not isinstance(value,dict):raise ValueError('メモはオブジェクトです')
            allowed={str(c['label']) for c in self.status(key)['result']['clusters']}
            if any(k not in allowed or not isinstance(v,str) or len(v)>10000 for k,v in value.items()):raise ValueError('メモの内容が不正です')
            temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
            return value
