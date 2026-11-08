/* Camera observer and reference recorder. Camera never modifies band inference. */
(()=>{
 const $=id=>document.getElementById(id);
 let stream,worker,ready=false,inFlight=false,lastFrame=-1,lastSent=-Infinity,alignment,recorder,sessionId;
 let lastDisplay='';
 let chunks=[],uploaded=new Set(),recording=false,stopped=false,uploadChain=Promise.resolve(),cameraError='';
 const clientNow=()=>performance.now()/1000;
 async function request(path,value){
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':window.liveSessionToken()},body:JSON.stringify(value)});
  const result=await response.json();if(!response.ok)throw Error(result.error||'Camera request failed');return result;
 }
 async function syncClock(){
  const start=clientNow(),response=await fetch('/api/clock',{cache:'no-store'}),value=await response.json(),end=clientNow();
  return {host_offset_seconds:value.host_uptime-(start+end)/2,uncertainty_seconds:(end-start)/2,client_sync_t:(start+end)/2};
 }
 function note(message){$('cameraStatus').textContent=message}
 async function enable(){
  $('enableCamera').disabled=true;
  try{
   if(!stream){stream=await navigator.mediaDevices.getUserMedia({video:{width:640,height:480,frameRate:30},audio:true});$('cameraVideo').srcObject=stream;await $('cameraVideo').play()}
   worker?.terminate();ready=false;inFlight=false;
   alignment=await syncClock();note('Loading independent hand observer…');
   worker=new Worker('/camera-worker.js');
   worker.onmessage=async event=>{
    const value=event.data;
    if(value.kind==='ready'){ready=true;note('Camera ready · right hand visible; audio/video record only with Record.');$('enableCamera').textContent='Camera enabled';window.dispatchEvent(new Event('camera-ready'));return}
    inFlight=false;
    if(value.kind==='error'){ready=false;$('enableCamera').disabled=false;note('Camera observer error: '+value.error);return}
    if(value.kind==='observation'){
     try{
      const response=await request('/api/camera/observations',{capture_id:recording?sessionId:null,alignment,observation:value});
      const name=response.posture.label;
      $('cameraAction').textContent='Camera: '+name+(name==='unknown'?' · keep your right hand clearly visible':' · independent estimate');
      $('cameraComparison').textContent=name==='unknown'?'Not enough visual evidence':response.agreement?'Matches band hand state':'Differs from band · saved for review when recording';
     }catch(error){cameraError=error.message;note('Camera logging error: '+cameraError)}
    }
   };
   worker.onerror=event=>{ready=false;inFlight=false;$('enableCamera').disabled=false;note('Camera observer failed: '+event.message)};
   worker.postMessage({kind:'init'});
   for(const track of stream.getTracks())track.onended=()=>{ready=false;note('Camera/microphone disconnected. Stop and save the recording.')};
   requestAnimationFrame(frameLoop);
  }catch(error){note('Camera not ready: '+error.message);$('enableCamera').disabled=false}
 }
 async function frameLoop(){
  const video=$('cameraVideo'),now=clientNow();
  if(ready&&!inFlight&&video.readyState>=2&&video.currentTime!==lastFrame&&now-lastSent>=.09){
   inFlight=true;lastFrame=video.currentTime;lastSent=now;
   try{const frame=await createImageBitmap(video);worker.postMessage({kind:'frame',frame,client_t:now,video_t:video.currentTime},[frame])}
   catch(error){inFlight=false;note('Camera frame error: '+error.message)}
  }
  requestAnimationFrame(frameLoop);
 }
 async function sendChunk(index){
  if(uploaded.has(index))return;
  const response=await fetch('/api/camera/chunk?capture_id='+encodeURIComponent(sessionId)+'&index='+index,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Session-Token':window.liveSessionToken()},body:chunks[index]});
  if(!response.ok){let message='Camera upload failed';try{message=(await response.json()).error||message}catch{}throw Error(message)}
  uploaded.add(index);chunks[index]=null; // The acknowledged chunk is durable on localhost; release browser memory.
 }
 window.CameraReference={
  get ready(){return ready},
  recordDisplay(display){
   if(!recording||!alignment)return;
   const signature=JSON.stringify(display);
   if(signature===lastDisplay)return;lastDisplay=signature;
   request('/api/camera/display',{capture_id:sessionId,client_t:clientNow(),alignment,display}).catch(error=>{if(recording)note('Display logging error: '+error.message)});
  },
  async abandon(){
   recording=false;
   if(recorder&&recorder.state!=='inactive'){await new Promise(resolve=>{recorder.onstop=resolve;recorder.stop()})}
   await uploadChain;await request('/api/camera/abandon',{capture_id:sessionId,reason:'participant_saved_emg_with_incomplete_reference'});
   recorder=null;chunks=[];stopped=true;
  },
  async start(capture){
   if(!ready)throw Error('Enable the camera and microphone first.');
   lastDisplay='';sessionId=capture.id;alignment=await syncClock();chunks=[];uploaded=new Set();stopped=false;cameraError='';uploadChain=Promise.resolve();
   const mime=['video/webm;codecs=vp8,opus','video/webm','video/mp4'].find(type=>MediaRecorder.isTypeSupported(type));
   if(!mime)throw Error('This browser cannot record camera references. Use Chrome.');
   recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:1200000});
   const client_t=clientNow();
   await request('/api/camera/start',{capture_id:sessionId,mime,alignment:{...alignment,record_client_start:client_t,video_start:$('cameraVideo').currentTime,tracks:stream.getTracks().map(t=>({kind:t.kind,settings:t.getSettings()}))}});
   recorder.ondataavailable=event=>{if(!event.data.size)return;const index=chunks.length;chunks.push(event.data);uploadChain=uploadChain.then(()=>sendChunk(index)).catch(error=>{cameraError=error.message;note('Camera upload pending · '+error.message)})};
   recorder.onerror=event=>{cameraError=event.error?.message||'Camera recorder failed';note(cameraError)};
   recorder.onstart=()=>{request('/api/camera/event',{capture_id:sessionId,event:'media_started',client_t:clientNow(),alignment}).catch(error=>{cameraError=error.message;note(cameraError)})};
   recorder.start(1000);recording=true;note('Recording synchronized camera/audio + independent hand observations.');
  },
  async stop(){
   if(!recorder)return;
   if(!stopped){await new Promise((resolve,reject)=>{recorder.onstop=resolve;try{recorder.stop()}catch(error){reject(error)}});stopped=true}
   await uploadChain;
   for(let i=0;i<chunks.length;i++)await sendChunk(i);
   await request('/api/camera/finish',{capture_id:sessionId,count:chunks.length,ended_client_t:clientNow()});
   recording=false;recorder=null;chunks=[];note('Camera/audio saved locally · ready for independent review.');
  }
 };
 $('enableCamera').onclick=enable;
})();
