import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';
const repo=resolve(new URL('..',import.meta.url).pathname);
test('actual client whole-scope suggestion → Chrome consent STOP → lost-response source report and physical cleanup',{timeout:120000},async()=>{
  const root=await mkdtemp(resolve(tmpdir(),'rlflow-agent-stop-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/agent_stop_request_server.py'),root],
    {stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser,page;const messages=[],waiters=[];child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{try{const v=JSON.parse(line),w=waiters.shift();if(w)w(v);else messages.push(v);}catch{stderr+=line;}});
  const next=()=>messages.length?Promise.resolve(messages.shift()):new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(Error(`owned fixture timeout: ${stderr}`)),45000);waiters.push(v=>{clearTimeout(timer);resolve(v);});});
  const control=async op=>{child.stdin.write(JSON.stringify(op)+'\n');return next();};
  try {
    const {origin,principal,phrase,projects}=await next();
    browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    page=await browser.newPage();const errors=[],posts=[];page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.method()==='POST' && r.url().endsWith('/forward-stop'))posts.push(JSON.parse(r.postData()));});
    await page.goto(origin);
    const before=await control({op:'inspect'});const saved=await control({op:'submit'});
    assert.equal(saved.status,'AWAITING_HUMAN');assert.equal(saved.stop_scope.items.length,2);
    assert.deepEqual(await control({op:'inspect'}),before);
    await page.locator('#principal').fill(principal);await page.locator('#passphrase').fill(phrase);await page.locator('#login-form button').click();
    await page.waitForFunction(()=>document.querySelector('#connection').textContent==='LIVE' && document.querySelector('#agent-request-list button'));
    await page.locator(`[data-request-id="${saved.request_id}"]`).click();
    await page.waitForFunction(()=>document.querySelector('#agent-request-view').textContent.includes('request_finite_stop'));
    const shown=JSON.parse(await page.locator('#agent-request-view').textContent());
    assert.deepEqual(shown.stop_scope,saved.stop_scope);assert.equal(shown.request_hash,saved.request_hash);
    assert.equal(await page.locator('#agent-request-forward').isDisabled(),true);assert.equal(posts.length,0);
    assert.ok((await page.locator('#agent-request-consent-text').textContent()).includes('不是仅停止当前项目'));
    await page.locator('#cpu-unit-run').click();
    await page.waitForFunction(()=>document.querySelector('#cpu-unit-run').disabled);
    let live;
    for(let i=0;i<50;i++){live=await control({op:'inspect'});if(live.pre_G_entered)break;await page.waitForTimeout(20);}
    assert.equal(live.pre_G_entered,true);assert.equal(live.release_entered,false);
    let dropped=false;
    await page.route('**/agent-requests/*/forward-stop',async route=>{
      assert.equal(dropped,false,'automatic/replacement STOP POST');dropped=true;
      const response=await route.fetch();assert.equal(response.status(),200);await route.abort('failed');
    });
    await page.locator('#agent-request-consent').check();await page.locator('#agent-request-forward').click();
    await page.waitForFunction(()=>document.querySelector('#agent-request-view').textContent.includes('"status": "STOPPED_AS_OF_RETURN"'));
    const report=await control({op:'report',request_id:saved.request_id});assert.equal(report.status,'STOPPED_AS_OF_RETURN');
    assert.deepEqual(JSON.parse(await page.locator('#agent-request-view').textContent()).result,report.result);
    assert.deepEqual(posts,[{request_hash:saved.request_hash,resume_cleanup:false}]);
    const actual=await control({op:'inspect'});assert.equal(actual.occupied,0);assert.equal(actual.all_cancelled,true);
    assert.equal(actual.producer_reaped,true);assert.equal(actual.all_FDs_closed,true);assert.equal(actual.release_entered,false);
    assert.equal(report.result.goal_completed,false);assert.equal(report.result.durable_aggregate_receipt,false);
    assert.equal(await page.locator('#agent-request-forward').isDisabled(),true);assert.equal(await page.locator('#agent-request-resume').isVisible(),false);
    await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.locator('#project-select').selectOption(projects[1]);
    assert.equal(await page.locator('#agent-request-view').textContent(),'');assert.equal(await page.locator('#agent-request-consent').isChecked(),false);
    await page.locator('#logout').click();assert.equal(await page.locator('#agent-request-view').textContent(),'');
    assert.deepEqual(errors,[]);assert.equal(posts.length,1);
    console.log('physical_STOP',JSON.stringify(actual));
  } finally {
    if(browser)await browser.close();child.stdin.end('{"op":"stop"}\n');
    await new Promise(resolve=>{if(child.exitCode!==null)return resolve();const timer=setTimeout(()=>child.kill('SIGTERM'),10000);child.once('exit',()=>{clearTimeout(timer);resolve();});});
    assert.equal(child.exitCode,0,stderr);await rm(root,{recursive:true,force:true});
  }
});
