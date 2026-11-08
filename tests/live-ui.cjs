const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes=new Map();function el(id){if(!nodes.has(id))nodes.set(id,{textContent:'',dataset:{},hidden:false});return nodes.get(id)}
let now=0,offline=false;
const state={gesture:'Nothing',connected:true,warming_up:false,fireballs:0,effort:null,band_file:'live.jsonl',errors:[]};
const camera={ready:true,async start(){},async stop(){},async abandon(){},recordDisplay(){}};
const context={document:{getElementById:el},window:{addEventListener(){},CameraReference:camera},performance:{now:()=>now},AbortController,console,
 navigator:{clipboard:{writeText:async path=>assert.equal(path,'live.jsonl')}},setInterval(){},setTimeout(){return 1},clearTimeout(){},
 fetch:async(path,options)=>{if(offline)throw Error('offline');
 if(options?.method==='POST'){
  const value=JSON.parse(options.body);
  if(path==='/api/equipment/shield'){state.gesture='Shield';return {ok:true,json:async()=>({switched:true,gesture:'Shield'})}}
  if(path.endsWith('/start'))state.recording={id:'test',path:'/tmp/capture',active:true,duration:0,corrections:0};
  else if(path.endsWith('/stop')){state.recording.active=false;state.recording.duration=12;}
  else if(path.endsWith('/mark')){state.recording.corrections++;state.recording.last_correction={gesture:value.gesture,timing:value.timing,reported_at:0,review_window_start:.8,review_window_end:4.8};return {ok:true,json:async()=>structuredClone(state.recording.last_correction)}}
  return {ok:true,json:async()=>structuredClone(state.recording)};
 }
 return {ok:true,json:async()=>structuredClone(state)}}};
vm.createContext(context);const html=fs.readFileSync('src/spelltrain/dashboard-live.html','utf8');
vm.runInContext(html.split('<script>')[1].split('</script>')[0],context);
(async()=>{
 await new Promise(r=>setImmediate(r));assert.equal(el('gesture').textContent,'Nothing');assert(el('setup').hidden);
 state.gesture='Shield';state.effort={label:'firm',index:.9};await vm.runInContext('refresh()',context);
 assert.equal(el('gesture').textContent,'Shield');assert.equal(el('effort').textContent,'Firm effort');
 state.gesture='Sword equipped';await vm.runInContext('refresh()',context);assert.equal(el('effort').textContent,'');
 state.gesture='Fireball equipped';state.fireballs=2;await vm.runInContext('refresh()',context);assert.equal(el('count').textContent,2);
 assert(el('hint').textContent.includes('not thrown'));
 assert(!el('switchShield').hidden);await el('switchShield').onclick();assert.equal(el('gesture').textContent,'Shield');assert(el('switchShield').hidden);
 el('reset').onclick();assert.equal(el('count').textContent,0);
 now=1000;vm.runInContext('render()',context);assert.equal(el('gesture').textContent,'Nothing');assert(!el('setup').hidden);
 offline=true;await vm.runInContext('refresh()',context);assert.equal(el('gesture').textContent,'Nothing');
 offline=false;state.gesture='Nothing';await vm.runInContext('refresh()',context);
 await el('record').onclick();assert(state.recording.active);assert(!el('corrections').hidden);
 await el('markShield').onclick();assert.equal(state.recording.corrections,1);assert(el('markStatus').textContent.includes('Shield'));
 state.recording.duration=1;await vm.runInContext('refresh()',context);assert(el('markStatus').textContent.startsWith('Go:'));
 state.recording.duration=5;await vm.runInContext('refresh()',context);assert(el('markStatus').textContent.includes('Choose the next'));
 await el('record').onclick();assert(!state.recording.active);assert(el('recordStatus').textContent.includes('Saved'));
 console.log('Live tester UI: gestures, shield effort, snap count, reset and stale/offline clearing passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
