// Optional real-Chrome check. Start frame_viewer first; Node 22+ is needed.
const {spawn}=require('node:child_process');
const fs=require('node:fs');const path=require('node:path');const os=require('node:os');const assert=require('node:assert/strict');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const candidates=[process.env.CHROME_PATH,...['PROGRAMFILES','PROGRAMFILES(X86)'].flatMap(k=>process.env[k]?[path.join(process.env[k],'Google/Chrome/Application/chrome.exe'),path.join(process.env[k],'Microsoft/Edge/Application/msedge.exe')]:[])].filter(Boolean);
const chrome=candidates.find(p=>fs.existsSync(p));if(!chrome)throw Error('Set CHROME_PATH to Chrome or Edge');
const url=process.argv[2]||'http://127.0.0.1:8769/';
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'frame-viewer-browser-'));
let socket,child;let id=0;const pending=new Map(),errors=[];
function send(method,params={},sessionId){return new Promise((resolve,reject)=>{const number=++id;const timeout=setTimeout(()=>{pending.delete(number);reject(Error('CDP timeout: '+method));},15000);pending.set(number,{resolve,reject,timeout});socket.send(JSON.stringify({id:number,method,params,...(sessionId?{sessionId}:{})}));});}
async function poll(fn){for(let i=0;i<100;i++){const result=await fn();if(result)return result;await sleep(100);}throw Error('Browser condition timed out');}
(async()=>{try{
 child=spawn(chrome,['--headless','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{windowsHide:true,stdio:'ignore'});
 child.on('error',error=>errors.push(error.message));
 const lines=await poll(async()=>{try{return fs.readFileSync(path.join(profile,'DevToolsActivePort'),'utf8').trim().split('\n');}catch{return null;}});
 socket=new WebSocket(`ws://127.0.0.1:${lines[0]}${lines[1]}`);await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
 socket.addEventListener('message',event=>{const value=JSON.parse(event.data);if(value.id){const task=pending.get(value.id);if(task){pending.delete(value.id);clearTimeout(task.timeout);value.error?task.reject(Error(JSON.stringify(value.error))):task.resolve(value.result);}}else if(value.method==='Runtime.exceptionThrown')errors.push(value.params.exceptionDetails.text+': '+(value.params.exceptionDetails.exception?.description||''));});
 const {targetId}=await send('Target.createTarget',{url:'about:blank'});const {sessionId}=await send('Target.attachToTarget',{targetId,flatten:true});await send('Runtime.enable',{},sessionId);await send('Page.enable',{},sessionId);await send('Page.navigate',{url},sessionId);
 const evaluate=async expression=>{const value=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true},sessionId);if(value.exceptionDetails)throw Error(JSON.stringify(value.exceptionDetails));return value.result.value;};
 await poll(()=>evaluate("document.querySelectorAll('.frame:not([hidden])').length===1 && [...document.querySelectorAll('.frame')].every(i=>i.complete&&i.naturalWidth>0)"));
 assert.equal(await evaluate("document.getElementById('loop').checked"),true);
 if(process.env.VARIATION_TEST==='1'){
  await send('Emulation.setDeviceMetricsOverride',{width:1500,height:1100,deviceScaleFactor:1,mobile:false},sessionId);
  await evaluate("document.querySelector('.variation-global').open=true;document.querySelector('.variation-panel').open=true;document.querySelector('.analyze').click()");
  await poll(()=>evaluate("[...panels.values()][0].v.status.textContent.includes('解析済み')"));
  await evaluate("(()=>{const p=[...panels.values()][0];p.v.feature.value='classes';p.v.feature.onchange()})()");
  await poll(()=>evaluate("![...panels.values()][0].v.overlay.hidden && [...panels.values()][0].v.overlay.complete"));
  await evaluate("[...panels.values()][0].v.stage.scrollIntoView({block:'center'})");
  const rect=await evaluate("(()=>{const r=[...panels.values()][0].v.svg.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};})()");
  const x=rect.x+rect.w*.3,y=rect.y+rect.h*.4;
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y},sessionId);
  await send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,clickCount:1,x,y},sessionId);
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',buttons:1,x:x+rect.w*.2,y:y+rect.h*.2},sessionId);
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,clickCount:1,x:x+rect.w*.2,y:y+rect.h*.2},sessionId);
  await poll(()=>evaluate("[...panels.values()][0].v.roi?.series.length===[...panels.values()][0].player.frames.length"));
  assert.equal(await evaluate("[...panels.values()][0].v.graph.querySelectorAll('polyline').length"),2);
  await evaluate("[...panels.values()][0].v.graph.querySelectorAll('rect')[1].dispatchEvent(new MouseEvent('click'))");
  await poll(()=>evaluate("[...panels.values()][0].player.index===1"));
  assert.equal(await evaluate("[...panels.values()][0].v.downloads.querySelectorAll('a').length"),2);
  await evaluate("document.querySelector('.aligned').checked=true;document.querySelector('.aligned').onchange()");
  await poll(()=>evaluate("[...panels.values()][0].v.status.textContent.includes('補正座標') && ![...panels.values()][0].v.overlay.hidden"));
  assert.equal(await evaluate("[...panels.values()][0].ui.frame.src.includes('feature=frame')"),true);
  await evaluate("(()=>{const p=[...panels.values()][0];p.v.feature.value='current_high';p.v.feature.onchange()})()");
  await poll(()=>evaluate("![...panels.values()][0].v.overlay.hidden && [...panels.values()][0].v.overlay.src.includes('current_high')"));
  await evaluate("document.querySelector('.aligned').checked=false;document.querySelector('.aligned').onchange()");
  await poll(()=>evaluate("[...panels.values()][0].v.status.textContent.includes('原座標')"));
  // An uncached settings change must clear old analysis and ROI overlays.
  await evaluate("(()=>{const input=document.querySelector('.variation-settings input');input.value='11';input.onchange()})()");
  assert.equal(await evaluate("[...panels.values()][0].v.status.textContent.includes('未解析') && [...panels.values()][0].v.overlay.hidden && [...panels.values()][0].v.roi===null"),true);
  await evaluate("(()=>{const input=document.querySelector('.variation-settings input');input.value='10';input.onchange();document.getElementById('first').click()})()");
  await poll(()=>evaluate("[...panels.values()][0].player.index===0"));
  console.log('PASS: variation job, classes overlay, real mouse ROI drag, graph seeking, exports and settings invalidation');
 }
 if(process.env.DISCOVERY_TEST==='1'){
  await send('Emulation.setDeviceMetricsOverride',{width:1500,height:1100,deviceScaleFactor:1,mobile:false},sessionId);
  await evaluate("document.querySelector('.discovery-panel').open=true");
  await poll(()=>evaluate("[...panels.values()][0].d.job!==null"));
  await evaluate("(()=>{const p=[...panels.values()][0],c=p.d.meta.clusters.find(c=>c.label>=0),i=p.d.meta.clusters.indexOf(c);p.d.clusterList.querySelectorAll('.cluster-card')[i].querySelector('button').click()})()");
  await poll(()=>evaluate("[...panels.values()][0].d.enabled.checked && ![...panels.values()][0].d.overlay.hidden && [...panels.values()][0].d.region?.indices.length===1"));
  assert.equal(await evaluate("[...panels.values()][0].d.examples.querySelectorAll('img').length"),5);
  await poll(()=>evaluate("[...panels.values()][0].d.examples.querySelector('img').complete && [...panels.values()][0].d.examples.querySelector('img').naturalWidth>0"));
  await evaluate("[...panels.values()][0].d.graph.querySelectorAll('circle')[1].dispatchEvent(new MouseEvent('click'))");
  await poll(()=>evaluate("[...panels.values()][0].player.frames[[...panels.values()][0].player.index]?.angle===[...panels.values()][0].d.meta.angles[1] && ![...panels.values()][0].player.loading"));
  assert.equal(await evaluate("[...panels.values()][0].d.region.angles.length"),await evaluate("[...panels.values()][0].d.meta.angles.length"));
  await evaluate("(()=>{const p=[...panels.values()][0];p.d.mode.value='median';p.d.mode.onchange();})()");
  await poll(()=>evaluate("[...panels.values()][0].ui.frame.src.includes('/api/discovery/image') && [...panels.values()][0].ui.frame.src.includes('angle='+[...panels.values()][0].d.meta.angles[1])"));
  await evaluate("[...panels.values()][0].v.stage.scrollIntoView({block:'center'})");
  const rectangle=await evaluate("(()=>{const r=[...panels.values()][0].d.svg.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};})()");
  const dx=rectangle.x+rectangle.w*.3,dy=rectangle.y+rectangle.h*.4;
  await send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,clickCount:1,x:dx,y:dy},sessionId);
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',buttons:1,x:dx+rectangle.w*.2,y:dy+rectangle.h*.2},sessionId);
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,clickCount:1,x:dx+rectangle.w*.2,y:dy+rectangle.h*.2},sessionId);
  await poll(()=>evaluate("[...panels.values()][0].d.region?.indices.length>1"));
  await evaluate("[...panels.values()][0].d.enabled.checked=false;[...panels.values()][0].d.enabled.onchange()");
  assert.equal(await evaluate("[...panels.values()][0].d.overlay.hidden && [...panels.values()][0].ui.frame.src.includes('/api/image')"),true);
  await evaluate("document.querySelector('.min-size').value='80';document.querySelector('.min-size').onchange()");
  assert.equal(await evaluate("[...panels.values()][0].d.meta===null && [...panels.values()][0].d.overlay.hidden"),true);
  await evaluate("document.querySelector('.min-size').value='40';document.querySelector('.min-size').onchange();document.getElementById('first').click()");
  await poll(()=>evaluate("[...panels.values()][0].d.job!==null && [...panels.values()][0].player.index===0"));
  console.log('PASS: unsupervised overlay, cluster selection, representative crops, phase-curve navigation, median image, mouse ROI and stale-result invalidation');
 }
 await evaluate("document.getElementById('selectAll').click()");
 await poll(()=>evaluate("panels.size===machines.length && [...panels.values()].every(p=>p.player.index===0 && p.ui.frame.complete && p.ui.frame.naturalWidth>0)"));
 // Exercise per-machine scope, including numeric angle boundaries.
 await evaluate("const p=panels.get(machines[0].name);p.ui.mode.value='all';p.ui.mode.onchange()");
 await poll(()=>evaluate("panels.get(machines[0].name).player.frames.length===machines[0].angles.flatMap(a=>a.frames).length && !panels.get(machines[0].name).player.loading"));
 assert.equal(await evaluate("panels.get(machines[0].name).player.frames[machines[0].angles[0].frames.length].angle"),await evaluate("machines[0].angles[1].angle"));
 await evaluate("document.getElementById('speed').value='10';document.getElementById('speed').onchange();globalThis.seen={};for(const [name,p] of panels){seen[name]=[];const original=p.player.display;p.player.display=(image,frame,index)=>{seen[name].push(index);original(image,frame,index);};}document.getElementById('last').click()");
 await poll(()=>evaluate("[...panels.values()].every(p=>!p.player.loading&&p.player.index===p.player.frames.length-1)"));
 await evaluate("document.getElementById('play').click()");
 await poll(()=>evaluate("[...panels.values()].every(p=>p.player.playing&&p.player.index>=1&&p.player.index<10)"));
 assert.equal(await evaluate("Object.values(seen).every(indices=>indices.includes(0)&&indices.includes(1))"),true);
 await evaluate("document.getElementById('play').click()");assert.equal(await evaluate("[...panels.values()].every(p=>!p.player.playing)"),true);
 await poll(()=>evaluate("[...panels.values()].every(p=>!p.player.loading)"));const positions=await evaluate("[...panels.values()].map(p=>p.player.index)");await sleep(500);assert.deepEqual(await evaluate("[...panels.values()].map(p=>p.player.index)"),positions);
 await evaluate("for(const input of document.querySelectorAll('#machines input'))input.checked=false;chooseMachines()");assert.equal(await evaluate("panels.size===0 && document.getElementById('play').disabled"),true);

 if(process.env.REVIEW_URL){
  const {targetId:reviewTarget}=await send('Target.createTarget',{url:'about:blank'});
  const {sessionId:reviewSession}=await send('Target.attachToTarget',{targetId:reviewTarget,flatten:true});
  await send('Runtime.enable',{},reviewSession);await send('Page.enable',{},reviewSession);
  await send('Emulation.setDeviceMetricsOverride',{width:1500,height:1100,deviceScaleFactor:1,mobile:false},reviewSession);
  await send('Page.navigate',{url:process.env.REVIEW_URL},reviewSession);
  const reviewEvaluate=async expression=>{const value=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true},reviewSession);if(value.exceptionDetails)throw Error(JSON.stringify(value.exceptionDetails));return value.result.value;};
  await poll(()=>reviewEvaluate("document.getElementById('raw')?.complete && document.getElementById('raw').naturalWidth>0 && items.length>0"));
  await reviewEvaluate("document.getElementById('status').value='ok';document.getElementById('status').onchange();document.getElementById('regionLabel').value='weft';document.getElementById('regionsLeft').scrollIntoView({block:'center'})");
  const rect=await reviewEvaluate("(()=>{const r=document.getElementById('regionsLeft').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};})()");
  const x=rect.x+rect.w*.25,y=rect.y+rect.h*.4;
  await send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,clickCount:1,x,y},reviewSession);
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',buttons:1,x:x+rect.w*.35,y:y+rect.h*.35},reviewSession);
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,clickCount:1,x:x+rect.w*.35,y:y+rect.h*.35},reviewSession);
  await poll(()=>reviewEvaluate("document.getElementById('saveState').textContent==='保存済み' && regions.length===1"));
  assert.equal(await reviewEvaluate("(async()=>{const r=await fetch('/api/export.csv');return r.ok && (await r.text()).includes('weft')})()"),true);
  await send('Page.reload',{},reviewSession);
  await poll(()=>reviewEvaluate("typeof regions!=='undefined' && regions.length===1 && document.getElementById('status').value==='ok'"));
  console.log('PASS: mask overlay, left-drag classification, save/reload and CSV export using synthetic data');
 }
 assert.deepEqual(errors,[]);console.log('PASS: Chrome loads all selected panels, all-angle scope, default looping, grouped play/pause, independent positions and deselection');
 }finally{
 if(socket?.readyState===WebSocket.OPEN){try{await send('Browser.close');}catch{}socket.close();}
 for(const task of pending.values())clearTimeout(task.timeout);
 if(child&&child.exitCode===null)child.kill();
 // Keep the isolated temporary profile for diagnostics; no user browser state is used.
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
