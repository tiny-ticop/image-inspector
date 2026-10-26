// Shared by the browser and dependency-free Node tests.
(function(root){
class Player {
 constructor({load,display,change,error,setTimer=(callback,delay)=>globalThis.setTimeout(callback,delay),clearTimer=id=>globalThis.clearTimeout(id)}){
  Object.assign(this,{load,display,change,error,setTimer,clearTimer});this.frames=[];this.index=-1;this.requested=-1;this.playing=false;this.loading=false;this.fps=2;this.loop=true;this.token=0;this.timer=null;
 }
 stop(){this.playing=false;this.clearTimer(this.timer);this.timer=null;this.change(this);}
 async select(frames){this.stop();this.frames=frames;this.index=-1;this.requested=-1;this.loading=false;this.token++;this.change(this);if(frames.length)await this.show(0);}
 async show(index){
  if(!this.frames.length)return;index=Math.max(0,Math.min(this.frames.length-1,index));const token=++this.token;const frame=this.frames[index];this.requested=index;this.loading=true;this.clearTimer(this.timer);this.timer=null;this.change(this);
  try{const image=await this.load(frame);if(token!==this.token)return;this.index=index;this.display(image,frame,index);this.loading=false;if(!this.loop&&index===this.frames.length-1)this.playing=false;this.change(this);this.schedule();}
  catch(error){if(token!==this.token)return;this.loading=false;this.stop();this.error(new Error(`${frame.id}: ${error.message}`));}
 }
 schedule(){this.clearTimer(this.timer);this.timer=null;if(this.playing&&!this.loading)this.timer=this.setTimer(()=>{this.timer=null;const next=this.index+1;if(next>=this.frames.length){if(this.loop)this.show(0);else this.stop();}else this.show(next);},1000/this.fps);}
 play(){if(!this.frames.length)return;this.playing=true;this.change(this);if(this.loading)return;if(this.index===this.frames.length-1||this.index<0)this.show(0);else this.schedule();}
 step(delta){this.stop();return this.show((this.requested<0?0:this.requested)+delta);}
 speed(fps){this.fps=fps;this.schedule();}
}
if(typeof module!=='undefined')module.exports=Player;else root.Player=Player;
})(globalThis);
