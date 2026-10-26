'use strict';
const $=id=>document.getElementById(id);
let items=[],reviews={},visible=[],index=0,current=null,dirty=false,timer=null,loading=false;
let regions=[],draft=[],drawing=false,draftLabel='weft';
const colors={weft:'#39aaff',warp:'#36d887',overlap:'#cf85ff',unknown:'#ffd84d'};
const labels={weft:'緯糸',warp:'経糸',overlap:'重なり',unknown:'判別不能'};
const names={unreviewed:'未確認',ok:'問題なし',fix:'要修正',hold:'判断保留'};
async function request(url,options){const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw new Error(data.error||`通信失敗 (${r.status})`);return data;}
function report(e){$('error').textContent=e.message||String(e);}
function options(id,values,all){const select=$(id);select.replaceChildren();if(all)select.add(new Option('すべて','all'));values.forEach(v=>select.add(new Option(v,v)));}
function updateAngles(){options('angle',[...new Set(items.filter(r=>$('machine').value==='all'||r.machine===$('machine').value).map(r=>r.angle))].sort((a,b)=>Number(a)-Number(b)),true);}
function rebuild(){visible=items.filter(r=>($('machine').value==='all'||r.machine===$('machine').value)&&($('angle').value==='all'||r.angle===$('angle').value)&&($('filter').value==='all'||(reviews[r.id]?.status||'unreviewed')===$('filter').value)&&(!$('issues').checked||r.issues.length));index=0;render();}
function progress(){const reviewed=items.filter(r=>reviews[r.id]&&reviews[r.id].status!=='unreviewed').length;$('progress').textContent=`確認済み ${reviewed} / ${items.length}`;}
function scale(){const value=$('zoom').value;document.querySelectorAll('.stage').forEach(s=>s.style.width=value==='fit'?'100%':`${(current?.width||1000)*Number(value)}px`);}
function render(){drawing=false;draft=[];current=visible[index]||null;dirty=false;$('error').textContent='';$('saveState').textContent='';$('position').value=current?index+1:'';$('position').max=visible.length;$('count').textContent=`/ ${visible.length} 枚`;$('prev').disabled=!current||index===0;$('next').disabled=!current||index===visible.length-1;['status','note','save'].forEach(id=>$(id).disabled=!current);progress();regions=JSON.parse(JSON.stringify(reviews[current?.id]?.regions||[]));drawRegions();regionList();
if(!current){$('filename').textContent='該当する画像がありません';$('detail').textContent='';['raw','base','mask'].forEach(id=>$(id).removeAttribute('src'));return;}
$('filename').textContent=current.filename;const r=reviews[current.id]||{};$('status').value=r.status||'unreviewed';$('note').value=r.note||'';
$('detail').textContent=`${current.machine} ／ ${current.angle}° ／ ${current.width}×${current.height} ／ 糸領域 ${current.ratio===null?'不明':(current.ratio*100).toFixed(2)+'%'}${current.issues.length?' ／ 注意：'+current.issues.join('・'):''}`;
const query='?id='+encodeURIComponent(current.id);$('raw').src='/api/raw'+query;$('base').src='/api/raw'+query;
if(current.issues.includes('マスクなし'))$('mask').removeAttribute('src');else $('mask').src='/api/mask'+query;
refreshClasses();scale();$('left').scrollTo(0,0);$('right').scrollTo(0,0);
}
let saving=null;
async function save(){if(saving){await saving;return save();}saving=persist();try{await saving;}finally{saving=null;}}
async function persist(){clearTimeout(timer);if(!current||!dirty)return;const key=current.id;const value={id:key,status:$('status').value,note:$('note').value,regions:JSON.parse(JSON.stringify(regions))};$('saveState').textContent='保存中…';try{const record=await request('/api/reviews',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});reviews[key]=record;if(current?.id===key&&$('status').value===value.status&&$('note').value===value.note&&JSON.stringify(regions)===JSON.stringify(value.regions)){dirty=false;$('saveState').textContent='保存済み';}refreshClasses();progress();}catch(e){$('saveState').textContent='未保存';report(e);throw e;}}
async function navigate(action){if(loading)return;loading=true;try{if(drawing)throw new Error('囲みを確定、または取消してから移動してください。');await save();action();}catch(e){report(e);}finally{loading=false;}}
function edit(){dirty=true;$('saveState').textContent='未保存';clearTimeout(timer);timer=setTimeout(()=>save().catch(()=>{}),500);}
$('status').onchange=edit;$('note').oninput=edit;$('save').onclick=()=>save().catch(()=>{});
$('prev').onclick=()=>navigate(()=>{index=Math.max(0,index-1);render();});$('next').onclick=()=>navigate(()=>{index=Math.min(visible.length-1,index+1);render();});
$('position').onchange=()=>{const desired=Number($('position').value);navigate(()=>{index=Math.max(0,Math.min(visible.length-1,desired-1));render();});};
$('machine').onchange=()=>navigate(()=>{updateAngles();rebuild();});['angle','filter','issues'].forEach(id=>$(id).onchange=()=>navigate(rebuild));
$('zoom').onchange=scale;$('opacity').oninput=()=>{$('mask').style.opacity=Number($('opacity').value)/100;$('opacityValue').textContent=$('opacity').value+'%';};$('overlay').onchange=()=>{$('mask').style.visibility=$('overlay').checked?'visible':'hidden';};
let syncing=false;['left','right'].forEach((id,i)=>$(id).addEventListener('scroll',()=>{if(syncing)return;syncing=true;const target=$(i?'left':'right');target.scrollLeft=$(id).scrollLeft;target.scrollTop=$(id).scrollTop;requestAnimationFrame(()=>syncing=false);}));
document.addEventListener('keydown',e=>{if(['INPUT','TEXTAREA','SELECT','BUTTON'].includes(e.target.tagName)||e.ctrlKey||e.metaKey||e.altKey)return;if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();$(e.key==='ArrowLeft'?'prev':'next').click();}});
document.querySelectorAll('a[download]').forEach(a=>a.addEventListener('click',e=>{if(dirty||saving){e.preventDefault();navigate(()=>{const link=document.createElement('a');link.href=a.href;link.download=a.download;link.click();});}}));
window.addEventListener('beforeunload',e=>{if(dirty||drawing){e.preventDefault();e.returnValue='';}});
['raw','base','mask'].forEach(id=>$(id).onerror=()=>{if(current)report(new Error('画像を読み込めません。サーバーとデータを確認してください。'));});
(async()=>{try{const [listing,saved]=await Promise.all([request('/api/inventory'),request('/api/reviews')]);items=listing.items;reviews=saved;options('machine',[...new Set(items.map(r=>r.machine))],true);updateAngles();rebuild();if(listing.warnings?.length)report(new Error(listing.warnings.join(' ')));if(listing.orphan_masks.length)report(new Error(`原画像のないマスク：${listing.orphan_masks.length}枚`));}catch(e){report(e);}})();

function drawRegions(){
 for(const id of ['regionsLeft','regionsRight']){
  const svg=$(id);svg.replaceChildren();svg.setAttribute('viewBox',`0 0 ${current?.width||1000} ${current?.height||650}`);svg.style.visibility=id==='regionsLeft'||$('showRegions').checked||drawing?'visible':'hidden';svg.classList.toggle('drawing',id==='regionsLeft');
  for(const r of [...regions,...(draft.length?[{label:draftLabel,points:draft,draft:true}]:[])]){
   const shape=document.createElementNS('http://www.w3.org/2000/svg',r.draft?'polyline':'polygon');shape.setAttribute('points',r.points.map(p=>p.join(',')).join(' '));shape.setAttribute('stroke',colors[r.label]);shape.setAttribute('stroke-width','2');shape.setAttribute('vector-effect','non-scaling-stroke');shape.setAttribute('fill',r.draft?'none':colors[r.label]);shape.setAttribute('fill-opacity',['mask_intersection','mask_connected'].includes(r.selection)?'0':'.16');if(!$('showRegions').checked&&!r.draft)shape.setAttribute('opacity','0');svg.append(shape);
   if(r.draft)for(const p of r.points){const dot=document.createElementNS(svg.namespaceURI,'circle');dot.setAttribute('cx',p[0]);dot.setAttribute('cy',p[1]);dot.setAttribute('r','3');dot.setAttribute('fill',colors[r.label]);svg.append(dot);}
  }
 }
 $('drawState').textContent=drawing?'左ボタンを離して登録 ／ Escで取消':'左画像で左ボタンを押しながらドラッグ。離すと接触した糸マスク全体を登録';
 $('cancel').disabled=!drawing;
 $('classOverlay').style.visibility=$('showRegions').checked?'visible':'hidden';
}
function refreshClasses(){if(!current){$('classOverlay').removeAttribute('src');return;}const query='?id='+encodeURIComponent(current.id);$('classOverlay').src='/api/labels-overlay.png'+query+'&v='+Date.now();$('labelsDownload').href='/api/labels.png'+query;}

function regionList(){const list=$('regionList');list.replaceChildren();regions.forEach((r,i)=>{const card=document.createElement('div');card.className='regionCard';card.style.borderLeftColor=colors[r.label];const title=document.createElement('span');title.textContent=`${i+1}. ${labels[r.label]}${['mask_intersection','mask_connected'].includes(r.selection)?'（接触した糸全体）':'（参考囲み）'}`;const note=document.createElement('input');note.placeholder='この領域の説明（任意）';note.value=r.note||'';note.maxLength=10000;note.oninput=()=>{r.note=note.value;edit();};const remove=document.createElement('button');remove.textContent='削除';remove.onclick=()=>{regions.splice(i,1);drawRegions();regionList();edit();};card.append(title,note,remove);list.append(card);});}

let anchor=null;
function imagePoint(e){const rect=$('regionsLeft').getBoundingClientRect();return [Math.max(0,Math.min(current.width-1,Math.round((e.clientX-rect.left)/rect.width*current.width))),Math.max(0,Math.min(current.height-1,Math.round((e.clientY-rect.top)/rect.height*current.height)))];}
function rectangle(a,b){return [[Math.min(a[0],b[0]),Math.min(a[1],b[1])],[Math.max(a[0],b[0]),Math.min(a[1],b[1])],[Math.max(a[0],b[0]),Math.max(a[1],b[1])],[Math.min(a[0],b[0]),Math.max(a[1],b[1])]];}
const surface=$('regionsLeft');
surface.oncontextmenu=e=>e.preventDefault();
surface.onpointerdown=e=>{if(e.button!==0||!current)return;e.preventDefault();anchor=imagePoint(e);draftLabel=$('regionLabel').value;draft=rectangle(anchor,anchor);drawing=true;surface.setPointerCapture(e.pointerId);drawRegions();};
surface.onpointermove=e=>{if(!drawing||!anchor)return;draft=rectangle(anchor,imagePoint(e));drawRegions();};
surface.onpointerup=e=>{if(!drawing||!anchor||e.button!==0)return;draft=rectangle(anchor,imagePoint(e));const points=draft;drawing=false;draft=[];anchor=null;drawRegions();if(points[1][0]-points[0][0]<1||points[2][1]-points[0][1]<1)return;regions.push({label:draftLabel,points,selection:'mask_connected',note:''});regionList();drawRegions();edit();};
function cancelRectangle(){drawing=false;draft=[];anchor=null;drawRegions();}
surface.onpointercancel=cancelRectangle;
$('cancel').onclick=cancelRectangle;
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&drawing)cancelRectangle();});
$('showRegions').onchange=drawRegions;
