const {chromium}=require('/tmp/spelltrain-browser-check/node_modules/playwright');
const {spawn,execFileSync}=require('child_process'),assert=require('assert'),fs=require('fs');
(async()=>{
 const server=spawn('.venv/bin/python',['tests/camera-browser-fixture.py'],{stdio:['ignore','pipe','inherit']});
 let browser;
 try{
  const url=await new Promise((resolve,reject)=>{server.stdout.once('data',d=>resolve(d.toString().trim()));server.once('exit',code=>reject(Error('Fixture exited '+code)))});
  browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream','--autoplay-policy=no-user-gesture-required']});
  const context=await browser.newContext({permissions:['camera','microphone']});const page=await context.newPage(),errors=[];
  page.on('response',response=>{if(response.status()>=400)console.log('HTTP',response.status(),response.url())});
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error')console.log('Browser:',message.text())});
  await page.goto(url);assert(await page.locator('#record').isDisabled());
  await page.locator('#enableCamera').click();
  try{await page.waitForFunction(()=>window.CameraReference?.ready,{},{timeout:45000})}catch(error){console.log('Camera status:',await page.locator('#cameraStatus').textContent());throw error}
  await page.locator('#record').click();
  await page.waitForFunction(()=>document.getElementById('record').textContent.includes('Stop'));
  await page.locator('#markShieldRelease').click();
  await page.waitForTimeout(2300);
  await page.locator('#record').click();
  await page.waitForFunction(()=>document.getElementById('recordStatus').textContent.startsWith('Saved'),{},{timeout:20000});
  const status=await (await page.request.get(url+'/api/status')).json();
  assert(status.recording.complete&&!status.recording.active);
  const directory=status.recording.path,metadata=JSON.parse(fs.readFileSync(directory+'/metadata.json'));
  assert(metadata.camera_reference?.complete);
  const rows=fs.readFileSync(directory+'/streams.jsonl','utf8').trim().split('\n').map(JSON.parse);
  assert(rows.some(row=>row.kind==='camera_observation'));
  assert(rows.some(row=>row.kind==='emg'));
  assert(rows.some(row=>row.kind==='browser_display'));
  assert(rows.some(row=>row.kind==='correction'&&row.correction.gesture==='Shield release'));
  const reference=await page.request.get(url+'/api/camera/reference?capture_id='+status.recording.id,{headers:{Range:'bytes=0-99'}});
  assert.equal(reference.status(),206);assert.equal((await reference.body()).length,100);
  const probe=JSON.parse(execFileSync('ffprobe',['-v','quiet','-show_streams','-of','json',directory+'/'+metadata.camera_reference.file]));
  assert(probe.streams.some(stream=>stream.codec_type==='video'));
  assert(probe.streams.some(stream=>stream.codec_type==='audio'));
  assert.equal(errors.length,0,errors.join('\n'));
  console.log(JSON.stringify({cameraReady:true,syntheticCapture:directory,cameraFrames:rows.filter(r=>r.kind==='camera_observation').length,recordedStreams:probe.streams.map(s=>s.codec_type),pageErrors:errors}));
 }finally{if(browser)await browser.close();server.kill('SIGINT')}
})().catch(error=>{console.error(error);process.exitCode=1});
