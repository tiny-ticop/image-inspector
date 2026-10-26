'use strict';
const $=id=>document.getElementById(id);
let machines=[];const panels=new Map();
function stopAll(){for(const panel of panels.values())panel.player.stop();}
function updateControls(){
 const players=[...panels.values()].map(p=>p.player).filter(p=>p.frames.length),playing=players.some(p=>p.playing);
 for(const id of ['first','prev','play','next','last'])$(id).disabled=!players.length;
 $('play').textContent=playing?'❚❚ まとめて一時停止':'▶ まとめて再生';
 $('state').textContent=!players.length?'再生対象なし':playing?'再生中':players.some(p=>p.loading)?'読み込み中…':'停止中';$('empty').hidden=panels.size>0;
}
function options(select,values){select.replaceChildren();for(const [value,text] of values)select.add(new Option(text,value));}
function makePanel(machine){
 const element=document.createElement('article');element.className='machine-panel';
 element.innerHTML=`<h2></h2><div class="panel-toolbar"><label>再生範囲<select class="mode"><option value="angle">角度指定</option><option value="all">機台内の全角度</option></select></label><label>角度<select class="angle"></select></label></div><div class="metadata"><strong class="angleInfo"></strong><span class="filename"></span></div><div class="panel-transport"><span class="position">0 / 0</span><input class="seek" type="range" min="0" max="0" value="0" aria-label="画像位置"><span class="status" role="status"></span></div><p class="panel-error" role="alert"></p><div class="viewport fit"><img class="frame" alt="機台の原画像" hidden><div class="placeholder">画像を読み込んでいます</div></div>`;
 element.querySelector('h2').textContent=machine.name;
 const ui={};for(const name of ['mode','angle','angleInfo','filename','position','seek','status','viewport','frame','placeholder'])ui[name]=element.querySelector('.'+name);ui.error=element.querySelector('.panel-error');
 options(ui.angle,machine.angles.map(a=>[a.name,`${a.angle}°（${a.frames.length}枚）`]));
 const panel={element,machine,ui,cache:new Map(),width:1000,player:null};
 function load(frame){
  if(panel.cache.has(frame.id))return panel.cache.get(frame.id);
  const promise=new Promise((resolve,reject)=>{const image=new Image();const timer=setTimeout(()=>{image.onload=null;image.onerror=null;reject(new Error('画像読み込みがタイムアウトしました'));},30000);image.onload=()=>{clearTimeout(timer);resolve(image);};image.onerror=()=>{clearTimeout(timer);reject(new Error('画像を読み込めません'));};image.src='/api/image?id='+encodeURIComponent(frame.id);});
  panel.cache.set(frame.id,promise);promise.catch(()=>{if(panel.cache.get(frame.id)===promise)panel.cache.delete(frame.id);});return promise;
 }
 function preload(){
  const keep=new Set(),player=panel.player;
  for(let offset=-2;offset<=2;offset++){const raw=player.index+offset,index=player.loop?(raw+player.frames.length)%player.frames.length:raw,frame=player.frames[index];if(frame){keep.add(frame.id);load(frame).catch(()=>{});}}
  for(const key of panel.cache.keys())if(!keep.has(key))panel.cache.delete(key);
 }
 panel.zoom=()=>{const fit=$('zoom').value==='fit';ui.viewport.classList.toggle('fit',fit);ui.frame.style.width=fit?'':`${panel.width*Number($('zoom').value)}px`;ui.frame.style.height=fit?'':'auto';};
 panel.player=new Player({load,display(image,frame){panel.width=image.naturalWidth;ui.frame.src=image.src;ui.frame.hidden=false;ui.placeholder.hidden=true;ui.filename.textContent=frame.filename;ui.angleInfo.textContent=`${frame.angle}°`;ui.error.textContent='';panel.zoom();preload();Variation.update(panel,frame);PatternDiscovery.update(panel,frame);},change(state){const n=state.frames.length;ui.position.textContent=`${state.index<0?0:state.index+1} / ${n}`;ui.seek.max=Math.max(0,n-1);ui.seek.value=Math.max(0,state.requested);ui.seek.disabled=!n;ui.status.textContent=state.loading?'読み込み中…':state.playing?'再生中':'停止中';updateControls();},error(error){stopAll();ui.error.textContent=error.message;if(ui.frame.hidden)ui.placeholder.textContent='画像を表示できません。上のエラーを確認してください。';}});
 panel.select=()=>{stopAll();Variation.reset(panel);PatternDiscovery.reset(panel);panel.cache.clear();ui.error.textContent='';ui.frame.hidden=true;ui.placeholder.hidden=false;ui.placeholder.textContent='画像を読み込んでいます';ui.filename.textContent='';ui.angleInfo.textContent='';ui.viewport.scrollTo(0,0);ui.angle.disabled=ui.mode.value==='all';const frames=ui.mode.value==='all'?machine.angles.flatMap(a=>a.frames):(machine.angles.find(a=>a.name===ui.angle.value)?.frames||[]);if(!frames.length)ui.placeholder.textContent='この範囲に画像はありません';panel.player.select(frames);};
 ui.mode.onchange=panel.select;ui.angle.onchange=panel.select;ui.seek.oninput=()=>{stopAll();panel.player.show(Number(ui.seek.value));};panel.player.loop=$('loop').checked;panel.player.fps=Number($('speed').value);
 Variation.attach(panel);PatternDiscovery.attach(panel);return panel;
}
function chooseMachines(){
 stopAll();const chosen=new Set([...$('machines').querySelectorAll('input:checked')].map(input=>input.value));
 for(const [name,panel] of panels){if(!chosen.has(name)){PatternDiscovery.dispose(panel);Variation.dispose(panel);panel.player.select([]);panel.cache.clear();panel.element.remove();panels.delete(name);}}
 for(const machine of machines){if(chosen.has(machine.name)){let panel=panels.get(machine.name);if(!panel){panel=makePanel(machine);panels.set(machine.name,panel);$('panels').append(panel.element);panel.select();}$('panels').append(panel.element);}}
 $('panels').classList.toggle('single',panels.size===1);updateControls();
}
function moveAll(getIndex){stopAll();for(const panel of panels.values())panel.player.show(getIndex(panel.player));}
$('play').onclick=()=>{const active=[...panels.values()].map(p=>p.player).filter(p=>p.frames.length);if(active.some(p=>p.playing))stopAll();else for(const player of active)player.play();};
$('prev').onclick=()=>moveAll(p=>Math.max(0,p.requested-1));$('next').onclick=()=>moveAll(p=>Math.min(p.frames.length-1,p.requested+1));$('first').onclick=()=>moveAll(()=>0);$('last').onclick=()=>moveAll(p=>p.frames.length-1);
$('speed').onchange=()=>{for(const panel of panels.values())panel.player.speed(Number($('speed').value));};$('loop').onchange=()=>{for(const panel of panels.values())panel.player.loop=$('loop').checked;};$('zoom').onchange=()=>{for(const panel of panels.values())panel.zoom();};
$('selectAll').onclick=()=>{for(const input of $('machines').querySelectorAll('input'))input.checked=true;chooseMachines();};
document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)||e.ctrlKey||e.altKey||e.metaKey)return;if(e.code==='Space'){if(e.target.tagName==='BUTTON')return;e.preventDefault();$('play').click();}else if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();$(e.key==='ArrowLeft'?'prev':'next').click();}});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopAll();});updateControls();
(async()=>{try{const response=await fetch('/api/inventory');if(!response.ok)throw new Error('画像一覧を読み込めません');const data=await response.json();machines=data.machines;$('total').textContent=`${machines.length}機台 ／ ${data.conditions}角度 ／ ${data.images.toLocaleString()}枚`;machines.forEach((machine,index)=>{const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.value=machine.name;check.checked=index===0;check.onchange=chooseMachines;label.append(check,document.createTextNode(machine.name));$('machines').append(label);});chooseMachines();}catch(error){stopAll();$('error').textContent=error.message;$('total').textContent='一覧の読み込みに失敗しました';}})();
