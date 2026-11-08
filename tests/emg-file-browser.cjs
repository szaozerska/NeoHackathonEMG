const {chromium}=require('../.local/browser-check/node_modules/playwright');
const {spawn}=require('child_process'),assert=require('assert'),fs=require('fs');
(async()=>{
 const server=spawn('.venv/bin/python',['tests/intent-browser-fixture.py','--emg-only'],{stdio:['ignore','pipe','inherit']});let browser;
 try{
  const url=await new Promise((resolve,reject)=>{server.stdout.once('data',data=>resolve(data.toString().trim()));server.once('exit',code=>reject(Error('Fixture exited '+code)))});
  browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
  const page=await browser.newPage();await page.goto(url);
  await page.waitForFunction(()=>!document.getElementById('start').disabled);
  assert.equal(await page.locator('#start').textContent(),'Start EMG-only session');
  await page.locator('#start').click();await page.locator('#recording').waitFor({state:'visible'});
  await page.locator('[data-motion="snap"]').click();
  await page.waitForFunction(()=>document.getElementById('selectedMotion').textContent.includes('snap'));
  await page.keyboard.down('Space');await page.waitForTimeout(100);await page.keyboard.up('Space');
  await page.waitForFunction(()=>!document.getElementById('stop').disabled);await page.locator('#stop').click();
  await page.waitForFunction(()=>document.getElementById('saved').textContent.startsWith('Saved'));
  const status=await (await page.request.get(url+'/api/status')).json();
  const meta=JSON.parse(fs.readFileSync(status.recording.path+'/metadata.json'));
  const truth=JSON.parse(fs.readFileSync(status.recording.path+'/truth-values.json'));
  assert.equal(meta.requested_capture_mode,'emg_only');assert.equal(meta.motion_context_available_at_start,false);
  assert(truth.intervals.some(row=>row.intended));
  console.log('EMG-only browser: Start enabled without gyro/orientation; session and Space labels saved.');
 }finally{if(browser)await browser.close();server.kill('SIGINT')}
})().catch(error=>{console.error(error);process.exitCode=1});
