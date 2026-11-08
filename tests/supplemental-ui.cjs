// Exercise the actual supplemental page: permission -> reference -> EMG -> upload/retry -> confirmation.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{textContent:'',hidden:false,disabled:false,dataset:{},
 querySelector:()=>element('dot'),play:async()=>{}});return elements.get(id)}
let now=0,permissionRequests=0,uploadAttempts=0,failUpload=true;
const tracks=[{kind:'audio',readyState:'live',stop(){this.readyState='ended'}},{kind:'video',readyState:'live',stop(){this.readyState='ended'}}];
const media={getTracks:()=>tracks,getAudioTracks:()=>tracks.filter(t=>t.kind==='audio'),getVideoTracks:()=>tracks.filter(t=>t.kind==='video')};
class Recorder{static isTypeSupported(){return true}constructor(stream,options){this.mimeType=options.mimeType;this.state='inactive'}start(){this.state='recording';this.onstart()}stop(){this.state='inactive';this.ondataavailable({data:new Blob(['x'.repeat(500)])});this.onstop()}}
class Reader{async readAsDataURL(blob){this.result='data:'+blob.type+';base64,'+Buffer.from(await blob.arrayBuffer()).toString('base64');this.onload()}}
const trials=[{id:'snap-1',title:'One snap',instruction:'Snap once',repetition:1,cues:[{at:0,text:'Wait'},{at:3,text:'SNAP NOW'}]},
 {id:'rest',title:'Relax',instruction:'Rest',repetition:1,cues:[]}];
const data={current:trials[0],active:null,pending:null,completed:0,total:2,rounds:2,results:[],session_id:'test'};
const clone=x=>JSON.parse(JSON.stringify(x));
const context={Blob,FileReader:Reader,MediaRecorder:Recorder,performance:{now:()=>now*1000},document:{getElementById:element},
 navigator:{mediaDevices:{getUserMedia:async()=>{permissionRequests++;return media}}},window:{addEventListener(){}},setInterval(){},
 fetch:async(path,options)=>{
 let response;
 if(path==='/api/status')response={now,emg_fresh:true,session:{band_file:'fresh.jsonl'}};
 else if(path==='/api/shield')response=data;
 else{
  const binary=path==='/api/reference-binary';
  const body=binary?{alignment:JSON.parse(decodeURIComponent(options.headers['X-Reference-Alignment']))}:JSON.parse(options.body);
  if(path==='/api/shield/start')response=data.active={id:'result-'+data.completed,motion:body.trial_id,start:now};
  else if(path==='/api/shield/stop'){response={...data.active,end:now,received:true,reference:null,confirmed:null};data.active=null;data.results.push(response);data.pending=response;}
  else if(path==='/api/reference-binary'){
   uploadAttempts++;assert.equal(Buffer.from(await options.body.arrayBuffer()).toString(),'x'.repeat(500));assert(body.alignment.recorder_start_ms<=body.alignment.start_request_ms);
   if(failUpload){failUpload=false;return {ok:false,json:async()=>({error:'Upload interrupted'})}}
   data.pending.reference={file:'reference.webm'};response=data.pending;
  }
  else if(path==='/api/shield/confirm'){
   assert(data.pending.reference);data.pending.confirmed=body.accepted;response=data.pending;data.pending=null;
   if(body.accepted){data.completed++;data.current=trials[data.completed]||null}
  }else throw Error(path);
 }
 return {ok:true,json:async()=>clone(response)};
 }};
const html=fs.readFileSync('src/spelltrain/dashboard-supplemental.html','utf8');
vm.createContext(context);vm.runInContext(html.split('<script>')[1].split('</script>')[0],context);
(async()=>{
 await new Promise(r=>setImmediate(r));assert(element('start').disabled);
 await element('enableReference').onclick();assert.equal(permissionRequests,1);assert(!element('start').disabled);
 await element('start').onclick();assert(!element('stop').hidden);
 now=3;await vm.runInContext('refresh()',context);assert.equal(element('cue').textContent,'SNAP NOW');
 now=6;await element('stop').onclick();
 assert.equal(data.completed,0);assert(element('confirm').disabled);assert(!element('referenceRetry').hidden);
 await element('referenceRetry').onclick();assert.equal(uploadAttempts,2);assert(!element('confirm').disabled);
 await element('confirm').onclick();assert.equal(data.completed,1);assert(element('start').disabled);
 now=12;await vm.runInContext('refresh()',context);
 await element('start').onclick();now=18;await element('stop').onclick();await element('confirm').onclick();
 assert.equal(data.completed,2);assert(!element('download').hidden);
 assert.equal(element('motion').textContent,'Extra examples collected.');
 console.log('Supplemental UI: media permission, timed cues, recording, upload failure/retry, confirmation, rest and completion passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
