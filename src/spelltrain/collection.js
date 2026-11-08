/* Trial cues are instructions; only explicit reports label performed actions. */
(()=>{
 const $=id=>document.getElementById(id);let live=null,busy=false,polling=false,lastReview=null,lastPhase=null,intentChoice='non_intended',markerAlignment=null,lastInteraction=-Infinity;
 async function api(action,value={}){
  const response=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':window.liveSessionToken()},body:JSON.stringify(value)});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Request failed');return result;
 }
 async function work(fn){if(busy)return;busy=true;$('error').textContent='';render();try{await fn()}catch(error){$('error').textContent=error.message}finally{busy=false;await refresh();render()}}
 async function syncMarkerClock(){const samples=[];for(let i=0;i<3;i++){const start=performance.now()/1000,response=await fetch('/api/clock',{cache:'no-store'}),clock=await response.json(),end=performance.now()/1000;samples.push({host_offset_seconds:clock.host_uptime-(start+end)/2,uncertainty_seconds:(end-start)/2})}markerAlignment=samples.sort((a,b)=>a.uncertainty_seconds-b.uncertainty_seconds)[0];return markerAlignment}
 const freshKind=kind=>live?.band_context?.[kind]?.age_seconds<1.5;
 function render(){
  if(!live)return;
  const connected=live.connected,session=live.collection,recording=live.recording;
  $('sensors').replaceChildren();
  for(const [name,good] of [['EMG',connected],['Orientation',freshKind('orientation')],['Gyro',freshKind('gyro')],['Camera',!!window.CameraReference?.ready]]){
   const span=document.createElement('span');span.className='chip '+(good?'good':'warn');span.textContent=name+' · '+(good?'live':'unavailable');$('sensors').append(span);
  }
  if(session?.annotation)intentChoice=session.annotation.label;const intended=intentChoice==='intended';$('intentToggle').textContent=intended?'Intended · ON':'Non-intended · OFF';$('intentToggle').setAttribute('aria-checked',String(intended));$('intentToggle').style.background=intended?'#23674b':'#842f38';$('intentToggle').disabled=busy;$('clickGuard').disabled=!!session;
  if(session?.annotation){const remaining=session.annotation.labeling_paused_seconds;$('intentToggleStatus').textContent=remaining>0?'Excluding button movement · labels resume in '+remaining.toFixed(1)+' s. Camera and raw sensors keep recording.':'Label interval active: '+intentChoice.replace('_','-')+'. A later click also removes its preceding guard interval.';}
  $('startSession').disabled=busy||!connected||($('useCamera').checked&&!window.CameraReference?.ready)||!!recording?.active;
  $('sessionSetup').hidden=!!session;$('trialPanel').hidden=!session;
  $('hand').disabled=!!session;$('useAudio').disabled=!!window.CameraReference?.ready;
  $('connectStream').disabled=busy||!!recording?.active;
  $('sessionPath').textContent=recording?'Local capture: '+recording.path:'';
  $('sourceStatus').textContent=live.input_kind==='stream'?'Full Kinesis stream selected. Sensor availability is shown above.':'Following Kinesis recording: '+live.band_file+'. Motion context is unavailable until the full feed is connected.';
  const orientation=live.band_context?.orientation?.event?.payload?.values;
  $('motionStatus').textContent=orientation&&freshKind('orientation')?'Latest wrist quaternion [w,x,y,z]: '+orientation.map(v=>v.toFixed(3)).join(', ')+'. This is wrist orientation, not an absolute palm angle.':'No fresh wrist orientation has arrived. Planned movement is not treated as measured rotation.';
  const names={none:'No equipped spell',pending_open:'Snap candidate → waiting for open hand',fireball:'Fireball equipped',sword:'Sword equipped'};
  $('equipment').textContent=connected?(names[live.equipment_preview?.item]||'Waiting for evidence'):'EMG unavailable · preview paused';
  for(const button of document.querySelectorAll('[data-failure]'))button.disabled=busy||!session;
  if(session){
   const trial=session.trial;
   $('phase').textContent=session.phase;$('progress').max=Math.max(1,session.total);$('progress').value=session.index;
   $('progressText').textContent=session.phase==='live'?'Continuous recording':Math.min(session.index+1,session.total)+' / '+session.total;
   $('trialTitle').textContent=trial?.title||(session.phase==='live'?'Live intent labeling':'Trial set complete');$('instruction').textContent=session.phase==='live'?'Move naturally while red. Toggle green for intended interaction, then return to red. No gesture names are needed. Keep the band hand visible; use your other hand for the button.':trial?.instruction||'Finish and save this session. Use the same wearing ID for another set until repositioning the band.';
   $('countdown').textContent=session.remaining==null?'':session.phase==='countdown'?'Ready · '+Math.ceil(session.remaining):session.phase==='active'?'GO · '+Math.ceil(session.remaining):'Review';
   $('nextTrial').hidden=!['ready','between'].includes(session.phase);$('nextTrial').disabled=busy||!connected;
   $('review').hidden=session.phase!=='review';$('finishSession').disabled=busy;const binary=trial?.kind==='intent';$('intentReport').hidden=!binary;$('actionReport').hidden=binary;$('actionIntentLabel').hidden=binary;
   $('savedProgress').textContent=session.saved_trials+' reports saved · '+session.usable_trials+' usable · '+session.failure_flags+' failure bookmarks';
   if(session.phase==='review'&&lastReview!==trial.trial_id){
    lastReview=trial.trial_id;$('actualSnaps').value='';$('intentLabel').value='';$('performed').checked=false;$('intent').checked=false;$('actualState').value='unknown';$('trialNote').value='';
    if(['open_hold','fist'].includes(trial.kind)){const labels=trial.camera_labels||{},total=Object.values(labels).reduce((a,b)=>a+b,0);for(const name of ['open','fist'])if(total>=20&&(labels[name]||0)/total>=.85){$('actualState').value=name;$('trialNote').value='Camera suggests '+name+'; participant must verify.';}}
   }
   if(session.phase==='review')$('trialEvidence').textContent=trial.packets+' EMG batches · '+trial.predicted_snaps+' model snap candidates · '+trial.orientation_samples+' orientation samples. Report what happened independently.';
   if(session.phase!==lastPhase){lastPhase=session.phase;if(session.phase==='active')$('instruction').focus?.()}
  }
  if(recording?.active)window.CameraReference?.recordDisplay({gesture:live.gesture,equipment:live.equipment_preview?.item,connected,phase:session?.phase});
  if(live.errors?.length)$('error').textContent=live.errors.join(' ');
 }
 async function refresh(){
  if(polling)return;polling=true;
  try{const response=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(2000)});if(!response.ok)throw Error('Tester unavailable');live=await response.json();render()}
  catch(error){if(live){live.connected=false;render()}$('error').textContent='Tester unavailable. Reconnect before continuing trials.'}
  finally{polling=false}
 }
 $('startSession').onclick=()=>work(async()=>{
  if($('useCamera').checked&&!window.CameraReference?.ready)throw Error('Enable the camera first, or turn off webcam reference for an EMG-only session.');
  await syncMarkerClock();const result=await api('collection/start',{wearing_session:$('wearing').value.trim(),role:$('role').value,focus:$('focus').value,hand:$('hand').value,initial_intent:intentChoice,interaction_guard:Number($('clickGuard').value)});
  if($('useCamera').checked)await window.CameraReference.start(result.recording);
  $('saveReport').textContent='';$('intentToggleStatus').textContent='Recording '+intentChoice.replace('_','-')+'. Camera and EMG stay live. '+$('clickGuard').value+' seconds around each interaction are excluded.';
 });
 $('nextTrial').onclick=()=>work(()=>api('collection/trial'));
 function report(discard,retry){return work(async()=>{
  const raw=$('actualSnaps').value;
  if(!discard&&live?.collection?.trial?.kind!=='intent'&&(!raw.trim()||!/^\d+$/.test(raw)))throw Error('Enter the actual snap count, including 0 for none.');
  await api('collection/confirm',{discard,retry,actual_snaps:discard||!raw.trim()?null:Number(raw),intent_label:$('intentLabel').value,performed:$('performed').checked,intent:$('intent').checked,hand_state:$('actualState').value,note:$('trialNote').value});
 })}
 $('confirmTrial').onclick=()=>report(false,false);$('retryTrial').onclick=()=>report(true,true);
 $('finishSession').onclick=()=>work(async()=>{
  try{await window.CameraReference?.stop()}catch(error){$('abandonVideo').hidden=false;throw error}
  const result=await api('collection/finish');
  $('saveReport').textContent='Saved locally: '+result.report.toggle_labeled_seconds.toFixed(1)+' seconds of guarded intent labels; '+result.report.usable_confirmed+' usable reports, '+result.report.failure_flags+' failure bookmarks. Model weights unchanged.';
 });
 $('abandonVideo').onclick=()=>work(async()=>{await window.CameraReference?.abandon();const result=await api('collection/finish');$('abandonVideo').hidden=true;$('saveReport').textContent='Saved EMG and '+result.report.usable_confirmed+' usable trial reports; video reference is incomplete.';});
 for(const button of document.querySelectorAll('[data-failure]'))button.onclick=()=>work(async()=>{await api('collection/flag',{kind:button.dataset.failure});$('flagStatus').textContent='Saved review bookmark: '+button.textContent;});
 $('connectStream').onclick=()=>work(async()=>{await api('source/stream',{url:$('streamUrl').value.trim()});$('streamUrl').value='';$('streamStatus').textContent='Connecting full feed. Confirm the live sensor indicators above.';});
 $('intentToggle').onclick=event=>{const client_t=performance.now()/1000,label=intentChoice==='intended'?'non_intended':'intended';if(!live?.collection){intentChoice=label;render();return}work(async()=>{if(!markerAlignment)await syncMarkerClock();await api('collection/intent-mark',{label,client_t,alignment:markerAlignment});$('intentToggleStatus').textContent='Marked '+label.replace('_','-')+'; excluded the button-transition region.';})};
 async function excludeInteraction(event){if(!live?.collection||!markerAlignment)return;if(event.type==='pointerdown'&&!event.target.closest('button,input,select,textarea,a'))return;const client_t=performance.now()/1000;if(client_t-lastInteraction<.2)return;lastInteraction=client_t;try{await api('collection/interaction',{client_t,alignment:markerAlignment,kind:event.type})}catch{}}
 document.addEventListener('pointerdown',excludeInteraction,true);document.addEventListener('keydown',excludeInteraction,true);
 $('hand').onchange=()=>{window.cameraTargetHand=$('hand').value};window.cameraTargetHand=$('hand').value;
 window.addEventListener('camera-ready',render);
 window.addEventListener('beforeunload',event=>{if(live?.recording?.active){event.preventDefault();event.returnValue=''}});
 setInterval(refresh,200);refresh();
})();
