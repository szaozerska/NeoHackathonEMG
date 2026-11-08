/* Space down begins an intended interval; Space up ends it. No camera or inference. */
(()=>{
 const $=id=>document.getElementById(id);
 let live=null,busy=false,polling=false,alignment=null,spaceHeld=false,pending=0,queue=Promise.resolve();
 async function api(action,value={}){
  const response=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':window.contributionToken},body:JSON.stringify(value)});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Request failed');return result;
 }
 async function sync(){
  const samples=[];
  for(let i=0;i<5;i++){const start=performance.now()/1000,response=await fetch('/api/clock',{cache:'no-store'}),clock=await response.json(),end=performance.now()/1000;samples.push({host_offset_seconds:clock.host_uptime-(start+end)/2,uncertainty_seconds:(end-start)/2})}
  alignment=samples.sort((a,b)=>a.uncertainty_seconds-b.uncertainty_seconds)[0];
 }
 function ownSession(){return !!live?.collection&&live?.recording_profile==='micah_emg'}
 function render(){
  if(!live)return;
  const active=ownSession(),intended=live.collection?.annotation?.label==='intended',motion=live.collection?.selected_motion;
  $('signal').dataset.live=String(!!live.connected);$('signal').textContent=live.connected?'EMG connected · 8 channels · 2,048 Hz nominal':'Waiting for fresh EMG from Kinesis';
  $('setup').hidden=active;$('recording').hidden=!active;
  $('start').disabled=busy||!live.connected||!!live.recording?.active;$('connect').disabled=busy||!!live.recording?.active;
  $('stop').disabled=busy||pending>0||spaceHeld;
  $('intent').className=intended?'intended':'';$('intentTitle').textContent=intended?'Intended · GREEN':'Non-intended · RED';
  $('intentInstruction').textContent=intended?'Perform the selected motion while holding Space. Release when finished.':'Rest or move naturally. Hold Space when ready for the selected action.';
  for(const button of document.querySelectorAll('[data-motion]')){
   const chosen=motion?.motion===button.dataset.motion&&(motion?.effort||'')===(button.dataset.effort||'');
   button.setAttribute('aria-pressed',String(chosen));button.style.background=chosen?'#365b7f':'';
   button.disabled=busy||pending>0||spaceHeld||intended;
  }
  $('selectedMotion').textContent=motion?'Next motion: '+motion.motion.replace('_',' ')+(motion.effort?' · '+motion.effort+' relative effort':''):'Select a motion before holding Space.';
  if(active){
   const remaining=live.collection.annotation.labeling_paused_seconds;
   $('guardState').textContent=!live.connected?'Signal gap: this missing period will not be labeled.':remaining>0?'Keyboard / mouse guard · '+remaining.toFixed(1)+' s remaining':'Label interval active';
   $('elapsed').textContent=live.recording.duration.toFixed(1)+' seconds recorded';$('markers').textContent=Math.max(0,live.collection.annotation.markers-1)+' key boundaries';$('path').textContent='Saving locally: '+live.recording.path;
  }
  $('source').textContent=live.input_kind==='stream'?'Using Kinesis live feed; this capture retains EMG only.':'Following Kinesis recording: '+live.band_file;
 }
 async function refresh(){
  if(polling||pending)return;polling=true;
  try{const response=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(2000)});if(!response.ok)throw Error();const value=await response.json();if(!pending)live=value;render()}
  catch{if(live){live.connected=false;render()}$('error').textContent='Localhost is unavailable. Key boundaries cannot be saved until it reconnects.'}
  finally{polling=false}
 }
 async function work(action){if(busy||pending)return;busy=true;$('error').textContent='';render();try{await action()}catch(error){$('error').textContent=error.message}finally{busy=false;await refresh();render()}}
 $('start').onclick=()=>work(async()=>{await sync();await api('collection/start',{profile:'micah_emg',wearing_session:$('wearing').value.trim(),role:$('role').value,focus:'live_intent',initial_intent:'non_intended',interaction_guard:Number($('guard').value)});$('saved').textContent='';$('start').blur();});
 for(const button of document.querySelectorAll('[data-motion]'))button.onclick=()=>work(async()=>{await api('collection/select-motion',{motion:button.dataset.motion,effort:button.dataset.effort||null});button.blur();});
 function mark(label,client_t){
  if(!ownSession()||!alignment)return;
  pending++;render();
  queue=queue.then(async()=>{const result=await api('collection/intent-mark',{label,client_t,alignment});if(live?.collection)live.collection.annotation=result;})
   .catch(error=>{$('error').textContent=error.message;})
   .finally(()=>{pending--;render();if(!pending)refresh();});
  return queue;
 }
 $('stop').onclick=()=>work(async()=>{const result=await api('collection/finish');$('saved').textContent='Saved '+result.report.intended_seconds.toFixed(1)+' intended seconds and '+result.report.non_intended_seconds.toFixed(1)+' non-intended seconds to '+result.recording.path+'. Labels: truth-values.json. Short guarded intervals are excluded.';$('stop').blur();spaceHeld=false;});
 $('connect').onclick=()=>work(async()=>{await api('source/stream',{url:$('streamUrl').value.trim()});$('streamUrl').value='';});
 async function interaction(kind){if(!ownSession()||!alignment)return;try{await api('collection/interaction',{kind,client_t:performance.now()/1000,alignment})}catch{}}
 document.addEventListener('keydown',event=>{
  if(event.target.closest('input,textarea,select,[contenteditable="true"]'))return;
  if(event.code==='Space'&&ownSession()){
   event.preventDefault();event.stopPropagation();if(event.repeat||spaceHeld||busy)return;
   if(!live.collection.selected_motion){$('error').textContent='Select Snap or a Shield/Sword effort first.';return;}
   spaceHeld=true;$('error').textContent='';mark('intended',performance.now()/1000);
  }else if(ownSession()&&!event.repeat)interaction('keyboard');
 },true);
 document.addEventListener('keyup',event=>{
  if(event.code!=='Space'||!spaceHeld)return;event.preventDefault();spaceHeld=false;mark('non_intended',performance.now()/1000);
 },true);
 document.addEventListener('pointerdown',event=>{if(event.target.closest('button,input,select,textarea,a'))interaction('mouse')},true);
 window.addEventListener('blur',()=>{if(ownSession()){interaction('focus_lost');if(spaceHeld){spaceHeld=false;mark('non_intended',performance.now()/1000)}}});
 window.addEventListener('focus',()=>{if(ownSession())interaction('focus_regained')});
 window.addEventListener('beforeunload',event=>{if(ownSession()){event.preventDefault();event.returnValue=''}});
 setInterval(refresh,150);refresh();
})();
