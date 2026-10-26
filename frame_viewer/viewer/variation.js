'use strict';
const Variation=(()=>{
 const attached=new Set(),jobs=new Map();let polling=false;
 const defaults={threshold:10,rare:.2,frequent:.5,dominance:2/3,window:9,sigma:12,top:60,border:8,aligned:false};
 const labels=['評価対象外','変動が小さい','広域明暗変動主体','少数画像の構造変化','中程度の出現割合の構造変化','多くの画像にある構造変化','混合・判別保留'];
 const colors=['#000000','#788c96','#ffbe28','#ff465a','#af64ff','#1ebee6','#aaaa46'];
 const features={raw:'原画像',excluded:'除外範囲（赤）',classes:'分類（集約）',std:'標準偏差（集約・輝度値）',mad:'MAD（集約・輝度値）',spread:'95–5%幅（集約・輝度値）',low_mean:'明暗成分（集約・輝度値）',high_mean:'構造成分（集約・輝度値）',low_frequency:'明暗の出現割合（集約）',high_frequency:'構造の出現割合（集約）',orientation:'方向のばらつき（集約）',current_low:'この画像の明暗差分',current_high:'この画像の構造差分'};
 const root=document.getElementById('variationControls');
 root.innerHTML=`<details class="variation-global"><summary>変動解析の条件・まとめて計算</summary><p class="hint">同じ機台・角度の画像群を解析します。全画面の中央値との差を測る探索で、正常・異常や物理原因は断定しません。</p><div class="variation-settings"></div><div class="toolbar"><button class="run-current">表示中の角度をまとめて解析</button><button class="run-all">選択機台の全角度を解析</button><label><input class="aligned" type="checkbox">平行移動補正後を解析・表示</label></div><p class="queue" role="status">解析結果を確認中…</p></details>`;
 const controls={};
 for(const [key,text,min,max,step] of [['threshold','差分閾値（0〜255）',.1,255,.5],['rare','少数変化の上限割合',.01,.99,.01],['frequent','多数変化の下限割合',.02,1,.01],['dominance','主体判定の割合',.51,1,.01],['window','小領域幅（奇数px）',1,51,2],['sigma','広域平滑化 sigma',.5,30,.5],['top','上端の除外px',0,500,1],['border','外周の除外px',0,500,1]]){
  const label=document.createElement('label');label.textContent=text;const input=document.createElement('input');Object.assign(input,{type:'number',min,max,step,value:defaults[key]});label.append(input);root.querySelector('.variation-settings').append(label);controls[key]=input;
 }
 controls.aligned=root.querySelector('.aligned');
 function config(){const value={};for(const [key,input] of Object.entries(controls))value[key]=key==='aligned'?input.checked:Number(input.value);return value;}
 function same(a,b){return Object.keys(defaults).every(key=>a[key]===b[key]);}
 async function api(url,body){const response=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await response.json();if(!response.ok)throw new Error(data.error||'解析通信エラー');return data;}
 function currentFrame(panel){return panel.player.frames[panel.player.index];}
 function findJob(panel,frame){return [...jobs.values()].find(job=>job.machine===panel.machine.name&&job.angle===String(frame.angle)&&job.result&&same(job.result.settings,config()))||[...jobs.values()].find(job=>job.machine===panel.machine.name&&job.angle===String(frame.angle)&&same(job.settings||{},config()));}
 async function poll(){if(polling)return;polling=true;try{
  const data=await api('/api/variation/jobs');let changed=false;
  for(const job of data.jobs){const old=jobs.get(job.id);if(!old||old.state!==job.state)changed=true;jobs.set(job.id,job);}
  const values=[...jobs.values()];root.querySelector('.queue').textContent=`完了 ${values.filter(j=>j.state==='complete').length} ／ 計算中・待機 ${values.filter(j=>['queued','running'].includes(j.state)).length} ／ 失敗 ${values.filter(j=>j.state==='failed').length}`;
  for(const panel of attached){const frame=currentFrame(panel);if(frame){const job=findJob(panel,frame);if(job&&job.state!=='complete')panel.v.status.textContent=`${job.message} ${Math.round(job.progress*100)}%`;if(changed)update(panel,frame);}}
 }catch(error){root.querySelector('.queue').textContent='解析APIに接続できません。サーバーを再起動してください：'+error.message;}finally{polling=false;}}
 async function submit(groups){try{if(!groups.length)throw Error('表示する機台・角度を選んでください');const data=await api('/api/variation/submit',{groups,settings:config()});for(const job of data.jobs)jobs.set(job.id,{...job,settings:config()});await poll();for(const panel of attached){const frame=currentFrame(panel);if(frame)update(panel,frame);}}catch(error){root.querySelector('.queue').textContent=error.message;}}
 root.querySelector('.run-current').onclick=()=>submit([...attached].map(panel=>({machine:panel.machine.name,angle:currentFrame(panel)?.angle})).filter(g=>g.angle!==undefined));
 root.querySelector('.run-all').onclick=()=>submit([...attached].flatMap(panel=>panel.machine.angles.filter(a=>a.frames.length>=3).map(a=>({machine:panel.machine.name,angle:a.name}))));
 for(const input of Object.values(controls))input.onchange=()=>{stopAll();for(const panel of attached){reset(panel);const frame=currentFrame(panel);if(frame){panel.ui.frame.src='/api/image?id='+encodeURIComponent(frame.id);update(panel,frame);}}};
 function url(job,feature,index=0){return '/api/variation/image?id='+job.id+'&feature='+feature+'&frame='+index;}
 function load(panel,src){if(panel.v.images.has(src))return panel.v.images.get(src);const promise=new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(Error('解析画像を読めません'));image.src=src;});panel.v.images.set(src,promise);while(panel.v.images.size>10)panel.v.images.delete(panel.v.images.keys().next().value);return promise;}
 function resize(panel){const v=panel.v;if(!v)return;const w=panel.width,h=panel.ui.frame.naturalHeight||650;const fit=document.getElementById('zoom').value==='fit';const width=fit?Math.min(panel.ui.viewport.clientWidth,panel.ui.viewport.clientHeight*w/h):w*Number(document.getElementById('zoom').value);v.stage.style.width=width+'px';v.stage.style.height=width*h/w+'px';v.svg.setAttribute('viewBox',`0 0 ${w} ${h}`);}
 function reset(panel){if(!panel.v)return;panel.v.token++;panel.v.job=null;panel.v.overlay.hidden=true;panel.v.svg.replaceChildren();panel.v.roi=null;panel.v.graph.replaceChildren();panel.v.summary.textContent='';panel.v.downloads.replaceChildren();panel.v.status.textContent='未解析';}
 function dispose(panel){reset(panel);panel.v.observer.disconnect();attached.delete(panel);}
 async function update(panel,frame){
  if(panel.d?.enabled.checked){reset(panel);return;}
  if(!panel.v)return;const v=panel.v,token=++v.token;v.overlay.hidden=true;const job=findJob(panel,frame);
  const activeId=job?.state==='complete'?job.id:null;
  if(v.job!==activeId){v.job=activeId;v.roiToken++;v.roi=null;v.svg.replaceChildren();v.graph.replaceChildren();v.summary.textContent='';v.downloads.replaceChildren();v.metaLink.removeAttribute('href');v.mapsLink.removeAttribute('href');}
  if(!job){v.status.textContent='未解析（現在の条件）';v.legend.textContent='';return;}
  if(job.state!=='complete'){v.status.textContent=job.state==='failed'?'失敗：'+job.message:job.message+' '+Math.round(job.progress*100)+'%';return;}
  const meta=job.result,index=meta.frames.findIndex(f=>f.id===frame.id);if(index<0){v.status.textContent='画像と解析結果が一致しません';return;}
  v.status.textContent=`解析済み ${meta.count}枚 ／ ${meta.settings.aligned?'補正座標':'原座標'} ／ ${meta.elapsed_seconds.toFixed(1)}秒`;
  const feature=v.feature.value;v.legend.replaceChildren();
  if(feature==='classes'){for(let i=1;i<labels.length;i++){const span=document.createElement('span');span.textContent='■ '+labels[i]+' ';span.style.color=colors[i];v.legend.append(span);}}
  else if(feature==='excluded')v.legend.textContent='赤：評価対象外（上端・外周・補正による無効範囲）';
  else if(feature!=='raw')v.legend.textContent=`共通表示スケール：0〜${meta.scales[feature]}${feature.includes('frequency')||feature==='orientation'?'（0〜1）':' 輝度値'} ／ 評価対象外は透明`;
  else v.legend.textContent='原画像。矩形をドラッグするとROIを集計します。';
  try{
   const base=meta.settings.aligned?await load(panel,url(job,'frame',index)):null;
   const layer=feature==='raw'?null:await load(panel,url(job,feature,feature.startsWith('current_')?index:0));
   if(token!==v.token)return;if(base)panel.ui.frame.src=base.src;
   if(layer){v.overlay.src=layer.src;v.overlay.hidden=false;}resize(panel);
   v.metaLink.href='/api/variation/download?id='+job.id+'&name=result.json';v.mapsLink.href='/api/variation/download?id='+job.id+'&name=maps.npz';
   for(const line of v.graph.querySelectorAll('.cursor'))line.setAttribute('x1',10+index/Math.max(1,meta.count-1)*480),line.setAttribute('x2',10+index/Math.max(1,meta.count-1)*480);
  }catch(error){if(token===v.token)v.status.textContent=error.message;}
 }
 function svgNode(tag,attrs){const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);return node;}
 function drawRect(panel,rectangle){panel.v.svg.replaceChildren();if(rectangle){const [x0,y0,x1,y1]=rectangle;panel.v.svg.append(svgNode('rect',{x:x0,y:y0,width:x1-x0,height:y1-y0,fill:'none',stroke:'#ffffff','stroke-width':2,'vector-effect':'non-scaling-stroke'}));}}
 async function roi(panel,rectangle){
  const v=panel.v,key=v.job;if(!key)return;const request=++v.roiToken;v.summary.textContent='ROIを集計中…';
  try{const data=await api('/api/variation/roi',{id:key,rectangle});if(v.job!==key||request!==v.roiToken)return;
   v.roi=data;v.summary.textContent=`ROI [${rectangle.join(', ')}] ／ 有効 ${data.valid_pixels}画素 ／ `+Object.entries(data.summary).map(([k,val])=>`${k}: ${val===null?'対象外':val.toFixed(3)}`).join(' ／ ')+'\n'+data.class_fraction.map((f,i)=>i?`${labels[i]} ${(f*100).toFixed(1)}%`:'').filter(Boolean).join(' ／ ');
   v.downloads.replaceChildren();for(const ext of ['csv','json']){const link=document.createElement('a');link.textContent='ROI '+ext.toUpperCase()+'出力';link.href='/api/variation/download?id='+key+'&roi='+data.export_id+'&name='+ext;link.download='roi.'+ext;v.downloads.append(link);}
   drawGraph(panel,data);
  }catch(error){if(v.job===key&&request===v.roiToken)v.summary.textContent=error.message;}
 }
 function drawGraph(panel,data){const svg=panel.v.graph;svg.replaceChildren();const rows=data.series,max=Math.max(1,...rows.flatMap(r=>[r.low,r.high]));svg.setAttribute('viewBox','0 0 500 150');
  svg.append(svgNode('path',{d:'M10 10V130H490',stroke:'#8fa4b5',fill:'none'}));
  for(const [key,color] of [['low','#d19400'],['high','#156fac']]){const points=rows.map((r,i)=>`${10+i/Math.max(1,rows.length-1)*480},${130-r[key]/max*110}`).join(' ');svg.append(svgNode('polyline',{points,stroke:color,'stroke-width':2,fill:'none'}));}
  for(let i=0;i<rows.length;i++){const target=svgNode('rect',{x:10+(i-.5)/Math.max(1,rows.length-1)*480,y:0,width:480/Math.max(1,rows.length-1),height:140,fill:'transparent',cursor:'pointer'});const title=svgNode('title',{});title.textContent=`${i+1}枚目 明暗 ${rows[i].low.toFixed(2)} / 構造 ${rows[i].high.toFixed(2)}`;target.append(title);target.onclick=()=>{stopAll();const index=panel.player.frames.findIndex(frame=>frame.id===rows[i].id);if(index>=0)panel.player.show(index);};svg.append(target);}
  const i=data.series.findIndex(r=>r.id===currentFrame(panel)?.id),x=10+Math.max(0,i)/Math.max(1,rows.length-1)*480;svg.append(svgNode('line',{class:'cursor',x1:x,x2:x,y1:5,y2:130,stroke:'#e03945','pointer-events':'none'}));
  const text=svgNode('text',{x:12,y:148,fill:'#486478','font-size':10});text.textContent=`1 → ${rows.length}枚（秒ではありません）　縦軸 0〜${max.toFixed(2)} 輝度値　黄:明暗／青:構造`;svg.append(text);
 }
 function attach(panel){
  const box=document.createElement('details');box.className='variation-panel';box.innerHTML=`<summary>変動解析・ROI</summary><div class="toolbar"><button class="analyze">この角度を解析</button><select class="feature" aria-label="変動の表示"></select><label>透明度<input class="opacity" type="range" min="0" max="100" value="60"></label></div><p class="analysis-status" role="status">未解析</p><p class="legend hint"></p><div class="toolbar"><a class="meta-link" download="result.json">計算条件JSON</a><a class="maps-link" download="maps.npz">特徴量NPZ</a><button class="clear-roi">ROI取消</button></div><p class="hint">画像上を左ドラッグして矩形ROIを指定。グラフをクリックすると該当画像へ移動します。</p><p class="roi-summary"></p><svg class="roi-graph"></svg><div class="roi-downloads"></div>`;
  panel.element.insertBefore(box,panel.ui.viewport);const stage=document.createElement('div');stage.className='variation-stage';panel.ui.frame.replaceWith(stage);stage.append(panel.ui.frame);const overlay=document.createElement('img');overlay.className='variation-overlay';overlay.hidden=true;overlay.alt='変動特徴';stage.append(overlay);const svg=svgNode('svg',{class:'roi-selector'});stage.append(svg);
  const v={stage,overlay,svg,images:new Map(),token:0,roiToken:0,job:null};panel.v=v;
  for(const [key,selector] of Object.entries({feature:'.feature',status:'.analysis-status',legend:'.legend',graph:'.roi-graph',summary:'.roi-summary',downloads:'.roi-downloads',metaLink:'.meta-link',mapsLink:'.maps-link'}))v[key]=box.querySelector(selector);
  for(const [key,text] of Object.entries(features))v.feature.add(new Option(text,key));
  box.querySelector('.analyze').onclick=()=>{const frame=currentFrame(panel);if(frame)submit([{machine:panel.machine.name,angle:frame.angle}]);};
  v.feature.onchange=()=>{const frame=currentFrame(panel);if(frame)update(panel,frame);};box.querySelector('.opacity').oninput=e=>overlay.style.opacity=Number(e.target.value)/100;overlay.style.opacity='.6';
  box.querySelector('.clear-roi').onclick=()=>{v.roiToken++;v.roi=null;svg.replaceChildren();v.graph.replaceChildren();v.summary.textContent='';v.downloads.replaceChildren();};
  const originalZoom=panel.zoom;panel.zoom=()=>{originalZoom();resize(panel);};v.observer=new ResizeObserver(()=>resize(panel));v.observer.observe(panel.ui.viewport);
  let start=null;const point=e=>{const r=stage.getBoundingClientRect(),h=panel.ui.frame.naturalHeight||650;return [Math.max(0,Math.min(panel.width,Math.round((e.clientX-r.left)/r.width*panel.width))),Math.max(0,Math.min(h,Math.round((e.clientY-r.top)/r.height*h)))];};
  const rect=(a,b)=>[Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])];
  svg.onpointerdown=e=>{if(e.button!==0||!v.job)return;stopAll();start=point(e);svg.setPointerCapture(e.pointerId);e.preventDefault();};svg.onpointermove=e=>{if(start)drawRect(panel,rect(start,point(e)));};svg.onpointerup=e=>{if(!start)return;const rectangle=rect(start,point(e));start=null;if(rectangle[2]>rectangle[0]&&rectangle[3]>rectangle[1]){drawRect(panel,rectangle);roi(panel,rectangle);}};svg.onpointercancel=()=>{start=null;drawRect(panel,v.roi?.rectangle);};
  attached.add(panel);
 }
 setInterval(poll,1200);poll();
 return {attach,update,reset,dispose,configuration:()=>({...config(),aligned:false})};
})();
