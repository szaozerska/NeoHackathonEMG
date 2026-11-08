const {chromium}=require('../.local/browser-check/node_modules/playwright');
const {spawn}=require('child_process'),assert=require('assert'),fs=require('fs');
(async()=>{
 const server=spawn('.venv/bin/python',['tests/intent-browser-fixture.py'],{stdio:['ignore','pipe','inherit']});let browser;
 try{
  const url=await new Promise((resolve,reject)=>{server.stdout.once('data',data=>resolve(data.toString().trim()));server.once('exit',code=>reject(Error('Fixture exited '+code)))});
  browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
  const page=await browser.newPage(),errors=[],requests=[];
  page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>requests.push(request.url()));
  await page.goto(url);await page.locator('#wearing').fill('micah-synthetic-01');
  await page.locator('#start').click();await page.locator('#recording').waitFor({state:'visible'});
  assert((await page.locator('#intentTitle').textContent()).includes('Non-intended'));
  await page.locator('[data-motion="shield_hold"][data-effort="medium"]').click();
  await page.waitForFunction(()=>document.getElementById('selectedMotion').textContent.includes('medium'));
  await page.waitForTimeout(1500);
  await page.keyboard.down('Space');await page.keyboard.down('Space');
  await page.waitForFunction(()=>document.getElementById('intentTitle').textContent.includes('GREEN'));
  assert(await page.locator('[data-motion="snap"]').isDisabled());
  await page.waitForTimeout(2200);await page.keyboard.up('Space');
  await page.waitForFunction(()=>document.getElementById('intentTitle').textContent.includes('RED'));
  const active=await (await page.request.get(url+'/api/status')).json();
  assert.equal(active.collection.annotation.markers,3); // initial red, key down, key up; no repeat toggle.
  await page.waitForTimeout(1600);await page.locator('#stop').click();
  await page.waitForFunction(()=>document.getElementById('saved').textContent.startsWith('Saved'));
  const status=await (await page.request.get(url+'/api/status')).json(),directory=status.recording.path;
  const truth=JSON.parse(fs.readFileSync(directory+'/truth-values.json'));
  assert(truth.intervals.some(row=>row.intended&&row.selected_motion.motion==='shield_hold'&&row.selected_motion.effort==='medium'));
  assert(truth.intervals.some(row=>!row.intended));assert.equal(truth.camera_used,false);
  const rows=fs.readFileSync(directory+'/streams.jsonl','utf8').trim().split('\n').map(JSON.parse);
  assert(!rows.some(row=>['camera_observation','prediction','decision','band_gyro'].includes(row.kind)));
  assert(!requests.some(path=>path.includes('/camera-')||path.includes('/vision/')));
  assert.equal(errors.length,0,errors.join('\n'));
  await page.screenshot({path:'.local/browser-check/micah-contribution.png',fullPage:true});
  console.log(JSON.stringify({emgOnly:true,spaceDownIntended:true,spaceUpNonIntended:true,repeatIgnored:true,motionAndEffortSaved:true,cameraRequested:false,syntheticCapture:directory}));
 }finally{if(browser)await browser.close();server.kill('SIGINT')}
})().catch(error=>{console.error(error);process.exitCode=1});
