// Classic worker retains importScripts for the pinned MediaPipe WASM loader.
const visionLibrary=import('/vision/vision_bundle.mjs');
let model;
self.onmessage=async event=>{
 const {kind,frame,client_t,video_t}=event.data;
 try{
  if(kind==='init'){
   const {FilesetResolver,HandLandmarker}=await visionLibrary;
   const vision=await FilesetResolver.forVisionTasks('/vision/wasm');
   model=await HandLandmarker.createFromOptions(vision,{baseOptions:{modelAssetPath:'/vision/hand_landmarker.task',delegate:'CPU'},runningMode:'VIDEO',numHands:2,minHandDetectionConfidence:.7,minHandPresenceConfidence:.7,minTrackingConfidence:.7});
   self.postMessage({kind:'ready'});
  }else if(kind==='frame'){
   try{
    const result=model.detectForVideo(frame,client_t*1000);
    const handed=result.handednesses||result.handedness||[];
    self.postMessage({kind:'observation',client_t,video_t,hands:(result.landmarks||[]).map((points,i)=>({landmarks:points.map(p=>[p.x,p.y,p.z]),world:(result.worldLandmarks[i]||[]).map(p=>[p.x,p.y,p.z]),handedness:handed[i]?.[0]?.categoryName,score:handed[i]?.[0]?.score||0}))});
   }finally{frame.close()}
  }
 }catch(error){self.postMessage({kind:'error',error:String(error)})}
};
