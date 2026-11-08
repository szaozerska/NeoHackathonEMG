/* Space down begins an intended interval; Space up ends it. No camera or inference. */
(()=>{
 const $=id=>document.getElementById(id),animationMode=document.body.dataset.testCondition==='animation',staticMode=animationMode||document.body.dataset.testCondition==='static';
 let live=null,busy=false,polling=false,alignment=null,spaceHeld=false,pending=0,queue=Promise.resolve(),holdStarted=null,lastHoldSeconds=0;
 if(animationMode&&new URLSearchParams(location.search).get('mode')==='dynamic')$('animationCondition').value='dynamic';
 const dynamicAnimation=()=>animationMode&&$('animationCondition').value==='dynamic';
 async function api(action,value={}){
  const response=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':window.contributionToken},body:JSON.stringify(value)});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Request failed');return result;
 }
 async function sync(){
  const samples=[];
  for(let i=0;i<5;i++){const start=performance.now()/1000,response=await fetch('/api/clock',{cache:'no-store'}),clock=await response.json(),end=performance.now()/1000;samples.push({host_offset_seconds:clock.host_uptime-(start+end)/2,uncertainty_seconds:(end-start)/2,client_sync_t:(start+end)/2,round_trip_seconds:end-start})}
  alignment=samples.sort((a,b)=>a.uncertainty_seconds-b.uncertainty_seconds)[0];if(ownSession())await api('collection/clock-sync',{alignment});
 }
 function ownSession(){return !!live?.collection&&live?.recording_profile==='micah_emg'}
 function render(){
  if(!live)return;
  const active=ownSession(),motionReady=live.band_context?.gyro?.age_seconds<1.5&&live.band_context?.orientation?.age_seconds<1.5&&!!live.sensor_timing?.forearm&&!!live.sensor_timing?.delivered_sensor_hz?.gyro&&!!live.sensor_timing?.delivered_sensor_hz?.orientation,intended=pending>0?spaceHeld:live.collection?.annotation?.label==='intended',motion=live.collection?.selected_motion;
  if(animationMode&&active&&live.collection_test_condition)$('animationCondition').value=live.collection_test_condition;
  $('signal').dataset.live=String(!!live.connected);$('signal').textContent=live.connected?'EMG connected · 8 channels · 2,048 Hz nominal':'Waiting for fresh EMG from Kinesis';
  $('setup').hidden=active;$('recording').hidden=!active;
  $('start').disabled=busy||!live.connected||!!live.recording?.active;$('start').textContent=motionReady?'Start full sensor session':'Start EMG-only session';$('connect').disabled=busy||!!live.recording?.active;
  $('stop').disabled=busy||pending>0||spaceHeld;
  $('intent').className=intended?'intended':'';$('intentTitle').textContent=intended?'Intended · GREEN':'Non-intended · RED';
  $('intentInstruction').textContent=animationMode?(intended?(dynamicAnimation()?'Cross your fingers, then tap thumb to pinky. Maintain the gesture while moving and rotating your arm naturally.':'Maintain Animation Gesture. Release Space when finished.'):(dynamicAnimation()?'Move and rotate your arm without the gesture. Hold Space at your first finger interaction.':'Rest normally. Hold Space when ready for Animation Gesture.')):(intended?(staticMode?'Keep your arm still and maintain the selected hold. Release when finished.':'Perform the selected motion while holding Space. Release when finished.'):(staticMode?'Rest with your arm still. Select Shield or Sword effort before holding Space.':'Rest or move naturally. Hold Space when ready for the selected action.'));
  if($('animationModeHint'))$('animationModeHint').textContent=dynamicAnimation()?'Dynamic: press Space at the first finger movement, cross the fingers, then tap thumb to pinky. Keep the entire sequence green. Move your arm and rotate through varied angles; release after undoing the gesture. In red, repeat arm/rotation movements without forming the gesture.':'Static: hold your arm comfortably steady. Press Space at the first finger interaction and keep the complete sequence green.';
  if($('holdElapsed')){const seconds=holdStarted===null?lastHoldSeconds:performance.now()/1000-holdStarted;$('holdElapsed').textContent=seconds.toFixed(1)+' / 30 seconds'+(seconds>=30?' · target reached; release when ready':'');}
  for(const button of document.querySelectorAll('[data-motion]')){
   const chosen=motion?.motion===button.dataset.motion&&(motion?.effort||'')===(button.dataset.effort||'');
   button.setAttribute('aria-pressed',String(chosen));button.style.background=chosen?'#365b7f':'';
   button.disabled=busy||pending>0||spaceHeld||intended;
  }
  $('selectedMotion').textContent=animationMode?'Animation Gesture · selected automatically':motion?'Next motion: '+motion.motion.replace('_',' ')+(motion.effort?' · '+motion.effort+' relative effort':''):staticMode?'Select a Shield/Sword effort before holding Space.':'Select a motion before holding Space.';
  if(active){
   $('guardState').textContent=!live.connected?'No fresh EMG · missing data is flagged separately.':intended?'Intended active now · cleanup deferred':'Non-intended baseline active · cleanup deferred';
   $('elapsed').textContent=live.recording.duration.toFixed(1)+' seconds recorded';$('markers').textContent=Math.max(0,live.collection.annotation.markers-1)+' key boundaries';$('path').textContent='Saving locally: '+live.recording.path;
  }
  const timing=live.sensor_timing||{},hz=timing.delivered_sensor_hz||{},hostHz=timing.host_delivery_hz||{},pose=timing.forearm;const number=(v,d=1)=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(d):'unavailable';$('timing').textContent='Arrival excess estimate: '+number(timing.arrival_delay_excess_estimate_seconds==null?null:timing.arrival_delay_excess_estimate_seconds*1000)+' ms · Kinesis→collector: '+number(timing.kinesis_to_python_seconds==null?null:timing.kinesis_to_python_seconds*1000)+' ms · Gyro / orientation: '+number(hz.gyro)+' / '+number(hz.orientation)+' Hz (band clock) · Host delivery: '+number(hostHz.gyro)+' / '+number(hostHz.orientation)+' Hz · Forearm elevation: '+number(pose?.forearm_elevation_degrees)+'° · Relative compass: '+number(pose?.forearm_compass_degrees)+'° · Key clock uncertainty: '+number(alignment?alignment.uncertainty_seconds*1000:null)+' ms';$('motionHint').textContent=motionReady?'Motion streams are live. Compass is relative; arrival delay is excess over the best observed offset, not absolute radio latency.':live.connected?'EMG-only capture is ready. Gyro/orientation are unavailable from a raw recording file. Connect the live feed below if you want full sensor context.':'Start enables when fresh EMG arrives. In Kinesis, enable Live EMG and start recording; keep it running. Motion context is optional for EMG-only capture.';
  $('source').textContent=live.input_kind==='stream'?'Using Kinesis live feed: EMG plus available timestamped motion/context.':'Following Kinesis recording: '+live.band_file;
 }
 async function refresh(){
  if(polling||pending)return;polling=true;
  try{const response=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(2000)});if(!response.ok)throw Error();const value=await response.json();if(!pending)live=value;render()}
  catch{if(live){live.connected=false;render()}$('error').textContent='Localhost is unavailable. Key boundaries cannot be saved until it reconnects.'}
  finally{polling=false}
 }
 async function work(action){if(busy||pending)return;busy=true;$('error').textContent='';render();try{await action()}catch(error){$('error').textContent=error.message}finally{busy=false;await refresh();render()}}
 $('start').onclick=()=>work(async()=>{if(dynamicAnimation()&&!('collection_test_condition' in live))throw Error('Open the updated dynamic collector at http://127.0.0.1:8805/animation?mode=dynamic');await sync();await api('collection/start',{profile:'micah_emg',test_condition:animationMode?'animation':staticMode?'static':'dynamic',animation_condition:animationMode?$('animationCondition').value:undefined,wearing_session:$('wearing').value.trim(),role:$('role').value,focus:'live_intent',initial_intent:'non_intended',interaction_guard:0,capture_mode:live.band_context?.gyro?.age_seconds<1.5&&live.band_context?.orientation?.age_seconds<1.5&&live.sensor_timing?.forearm&&live.sensor_timing?.delivered_sensor_hz?.gyro&&live.sensor_timing?.delivered_sensor_hz?.orientation?'full_context':'emg_only',clock_alignment:alignment});$('saved').textContent='';lastHoldSeconds=0;holdStarted=null;$('start').blur();});
 for(const button of document.querySelectorAll('[data-motion]'))button.onclick=()=>work(async()=>{await api('collection/select-motion',{motion:button.dataset.motion,effort:button.dataset.effort||null});button.blur();});
 function mark(label,client_t){
  if(!ownSession()||!alignment)return;
  const eventAlignment={...alignment};pending++;render();
  queue=queue.then(async()=>{const result=await api('collection/intent-mark',{label,client_t,alignment:eventAlignment});if(live?.collection)live.collection.annotation=result;})
   .catch(error=>{$('error').textContent=error.message;})
   .finally(()=>{pending--;render();if(!pending)refresh();});
  return queue;
 }
 $('stop').onclick=()=>work(async()=>{const result=await api('collection/finish');$('saved').textContent='Saved '+result.report.intended_seconds.toFixed(1)+' intended seconds and '+result.report.non_intended_seconds.toFixed(1)+' non-intended seconds to '+result.recording.path+'. Labels: truth-values.json. All reported intervals are retained for later post-processing.';$('stop').blur();spaceHeld=false;});
 $('connect').onclick=()=>work(async()=>{await api('source/stream',{url:$('streamUrl').value.trim()});$('streamUrl').value='';});
 async function interaction(kind){if(!ownSession()||!alignment)return;try{await api('collection/interaction',{kind,client_t:performance.now()/1000,alignment})}catch{}}
 document.addEventListener('keydown',event=>{
  if(event.target.closest('input,textarea,select,[contenteditable="true"]'))return;
  if(event.code==='Space'&&ownSession()){
   event.preventDefault();event.stopPropagation();if(event.repeat||spaceHeld||busy)return;
   if(!live.collection.selected_motion){$('error').textContent='Select Snap or a Shield/Sword effort first.';return;}
   spaceHeld=true;holdStarted=performance.now()/1000;$('error').textContent='';mark('intended',holdStarted);
  }else if(ownSession()&&!event.repeat)interaction('keyboard');
 },true);
 document.addEventListener('keyup',event=>{
  if(event.code!=='Space'||!spaceHeld)return;event.preventDefault();spaceHeld=false;const released=performance.now()/1000;lastHoldSeconds=released-holdStarted;holdStarted=null;mark('non_intended',released);
 },true);
 document.addEventListener('pointerdown',event=>{if(event.target.closest('button,input,select,textarea,a'))interaction('mouse')},true);
 window.addEventListener('blur',()=>{if(ownSession()){interaction('focus_lost');if(spaceHeld){spaceHeld=false;const released=performance.now()/1000;lastHoldSeconds=released-holdStarted;holdStarted=null;mark('non_intended',released)}}});
 window.addEventListener('focus',()=>{if(ownSession())interaction('focus_regained')});
 window.addEventListener('beforeunload',event=>{if(ownSession()){event.preventDefault();event.returnValue=''}});
 setInterval(refresh,150);setInterval(()=>{if(ownSession()&&!pending&&!busy)sync().catch(error=>{$('error').textContent='Clock recalibration failed: '+error.message})},30000);refresh();
})();
