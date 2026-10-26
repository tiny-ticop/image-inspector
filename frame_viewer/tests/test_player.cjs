const assert=require('node:assert/strict');
const Player=require('../viewer/player.js');
const frames=[{id:'angle95/a'},{id:'angle95/b'},{id:'angle96/a'}];
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup(load=async f=>f.id){let timer=null;const displayed=[],errors=[];let delay;const player=new Player({load,display:(_,f)=>displayed.push(f.id),change:()=>{},error:e=>errors.push(e.message),setTimer:(fn,ms)=>{timer=fn;delay=ms;return fn;},clearTimer:()=>{timer=null;}});return {player,displayed,errors,fire:async()=>{const fn=timer;timer=null;if(fn)await fn();await tick();},delay:()=>delay};}
(async()=>{
 // Browser timer functions require the Window receiver. Injected test timers
 // previously hid the Illegal invocation error that stopped initial rendering.
 const originalSet=globalThis.setTimeout,originalClear=globalThis.clearTimeout;
 try{
  globalThis.setTimeout=function(callback,delay){assert.equal(this,globalThis);return 123;};
  globalThis.clearTimeout=function(id){assert.equal(this,globalThis);};
  const native=new Player({load:async frame=>frame.id,display:()=>{},change:()=>{},error:e=>{throw e;}});
  await native.select(frames);assert.equal(native.index,0);native.play();native.stop();
 }finally{globalThis.setTimeout=originalSet;globalThis.clearTimeout=originalClear;}
 const s=setup();assert.equal(s.player.loop,true);s.player.loop=false;await s.player.select(frames);assert.equal(s.player.fps,2);s.player.play();assert.equal(s.delay(),500);await s.fire();await s.fire();assert.deepEqual(s.displayed,frames.map(f=>f.id));assert.equal(s.player.playing,false);
 s.player.loop=true;s.player.play();await tick();assert.equal(s.player.index,0);s.player.speed(10);assert.equal(s.delay(),100);await s.fire();await s.fire();await s.fire();assert.equal(s.player.index,0);s.player.stop();
 await s.player.step(1);assert.equal(s.player.index,1);await s.player.show(2);assert.equal(s.player.index,2);await s.player.select([]);assert.equal(s.player.index,-1);s.player.play();assert.equal(s.player.playing,false);
 // Two image requests finish in reverse order: newest selection must win.
 const pending=new Map();const r=setup(f=>new Promise(resolve=>pending.set(f.id,resolve)));const first=r.player.select(frames);const next=r.player.show(1);pending.get(frames[1].id)('second');await next;pending.get(frames[0].id)('first');await first;assert.deepEqual(r.displayed,[frames[1].id]);
 // Switching scope invalidates outstanding reads.
 const old=r.player.show(2);await r.player.select([]);pending.get(frames[2].id)('old');await old;assert.equal(r.player.index,-1);
 const failed=setup(async()=>{throw Error('unreadable');});await failed.player.select(frames);assert.equal(failed.player.playing,false);assert.match(failed.errors[0],/angle95\/a.*unreadable/);
 // Stopping during a read allows the frame to finish, but schedules no next frame.
 let release;const slow=setup(()=>new Promise(resolve=>release=resolve));const waiting=slow.player.select(frames);slow.player.play();slow.player.stop();release('image');await waiting;await slow.fire();assert.equal(slow.player.index,0);assert.equal(slow.player.playing,false);
 // Different machine lengths loop independently and can be stopped together.
 const short=setup(),long=setup();await short.player.select(frames.slice(0,2));await long.player.select(frames);short.player.play();long.player.play();for(let i=0;i<4;i++){await short.fire();await long.fire();}assert.equal(short.player.index,0);assert.equal(long.player.index,1);assert.equal(short.player.playing,true);assert.equal(long.player.playing,true);short.player.stop();long.player.stop();await short.fire();await long.fire();assert.equal(short.player.playing,false);assert.equal(long.player.playing,false);
 console.log('PASS: order, angle boundary, speed, loop, stop, seek, empty scope, stale reads, read errors');
})().catch(e=>{console.error(e);process.exitCode=1;});
