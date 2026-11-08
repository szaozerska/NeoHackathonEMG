// Exercise the real inline UI script without browser dependencies.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{textContent:'',hidden:false,disabled:false,querySelector:()=>element('dot')});return elements.get(id)}
const trials=[{id:'rest',title:'Relax',instruction:'Rest',repetition:1},{id:'firm-sharp',title:'Firm sharp push',instruction:'Brace and push',repetition:1}];
let now=0,stale=true,tokenRecovered=false,serial=0,fail=false;
const data={current:trials[0],active:null,pending:null,completed:0,total:2,results:[],session_id:'test'};
const clone=x=>JSON.parse(JSON.stringify(x));
const context={console,performance:{now:()=>0},document:{getElementById:element},window:{addEventListener(){}},setInterval(){},
 fetch:async(path,options)=>{
  if(path==='/'){tokenRecovered=true;return {ok:true,text:async()=>"const token='new-token';"};}
  if(options?.method==='POST'&&stale){stale=false;return {ok:false,status:403,json:async()=>({error:'Invalid session token'})};}
  let response;
  if(path==='/api/status')response={now,emg_fresh:true,session:{mode:'emg_only'}};
  else if(path==='/api/shield')response=data;
  else {
   assert.equal(options.headers['X-Session-Token'],'new-token');
   const body=JSON.parse(options.body);
   if(path.endsWith('/start')){assert.equal(body.trial_id,data.current.id);response=data.active={id:String(++serial),motion:body.trial_id,start:now};}
   else if(path.endsWith('/stop')){now+=5;response={...data.active,end:now,received:!fail,message:fail?'No EMG received.':'Received.',confirmed:null,needs_paired_quest:true};data.results.push(response);data.active=null;if(!fail)data.pending=response;}
   else if(path.endsWith('/confirm')){const row=data.results.find(r=>r.id===body.id);row.confirmed=body.accepted;data.pending=null;if(body.accepted){data.completed++;data.current=trials[data.completed]||null;}response=row;}
   else throw Error('Unexpected route '+path);
  }
  return {ok:true,json:async()=>clone(response)};
 }};
const html=fs.readFileSync('src/spelltrain/dashboard.html','utf8');
vm.createContext(context);vm.runInContext(html.split('<script>')[1].split('</script>')[0],context);
(async()=>{
 await new Promise(r=>setImmediate(r));
 assert.equal(element('motion').textContent,'Relax');
 await element('start').onclick();assert(tokenRecovered);assert(!element('stop').hidden);
 fail=true;await element('stop').onclick();assert.equal(element('result').textContent,'No EMG received.');assert(element('confirm').hidden);assert.equal(data.completed,0);
 now+=6;await vm.runInContext('refresh()',context);fail=false;
 await element('start').onclick();await element('stop').onclick();assert(!element('confirm').hidden);assert.equal(data.completed,0);
 await element('retry').onclick();assert.equal(data.completed,0);assert.equal(data.current.id,'rest');assert(element('start').disabled);
 for(let i=0;i<2;i++){
  now+=6;await vm.runInContext('refresh()',context);assert(!element('start').disabled);
  await element('start').onclick();await element('stop').onclick();
  assert.equal(element('result').textContent,'Received.');await element('confirm').onclick();
 }
 assert.equal(data.completed,2);assert.equal(element('motion').textContent,'Spell examples collected.');assert(!element('download').hidden);
 console.log('Shield UI: token recovery, recording, failed capture, confirmation, retry, rest, progression and completion passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
