import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';
const repo=resolve(new URL('..',import.meta.url).pathname);
const phrase='synthetic HTTP control fixture passphrase';
test('actual client suggestion → explicit Chrome human forwarding → original DRAFT report; private clearing and lost response',{timeout:90000},async()=>{
  const root=await mkdtemp(resolve(tmpdir(),'rlflow-agent-request-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/agent_request_server.py'),root],
    {stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser,page;const messages=[],waiters=[];
  child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{try{const value=JSON.parse(line),w=waiters.shift();if(w)w(value);else messages.push(value);}catch{stderr+=line;}});
  const next=()=>messages.length ? Promise.resolve(messages.shift()) : new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error(`fixture response timeout ${stderr}`)),10000);waiters.push(v=>{clearTimeout(timer);resolve(v);});});
  const control=async op=>{child.stdin.write(JSON.stringify(op)+'\n');return next();};
  try {
    const {origin}=await next();
    browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    page=await browser.newPage();const errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.method()==='POST' && r.url().endsWith('/forward'))writes.push(r.postData());});
    await page.goto(origin);
    const saved=await control({op:'submit',goal_id:'browser_goal_a',key:'browser_original_a'});
    assert.equal(saved.status,'AWAITING_HUMAN');assert.equal((await control({op:'inspect'})).version,0);
    const login=async principal=>{
      await page.locator('#principal').fill(principal);await page.locator('#passphrase').fill(phrase);await page.locator('#login-form button').click();
      await page.waitForFunction(()=>document.querySelector('#connection').textContent==='LIVE');
    };
    await login('viewer');assert.equal(await page.locator('#agent-request-refresh').isDisabled(),true);
    assert.equal(await page.locator('#agent-request-view').textContent(),'');await page.locator('#logout').click();
    await login('operator');await page.waitForFunction(()=>document.querySelector('#agent-request-list button'));
    await page.locator(`[data-request-id="${saved.request_id}"]`).click();
    await page.waitForFunction(()=>document.querySelector('#agent-request-view').textContent.includes('browser_goal_a'));
    const shown=JSON.parse(await page.locator('#agent-request-view').textContent());
    assert.equal(shown.request_hash,saved.request_hash);assert.equal(shown.status,'AWAITING_HUMAN');
    assert.equal(await page.locator('#agent-request-view img').count(),0);assert.equal(await page.evaluate(()=>window.requestInjected),undefined);
    assert.equal(await page.locator('#agent-request-forward').isDisabled(),true);
    let dropped=false;
    await page.route('**/agent-requests/*/forward',async route=>{
      if(!dropped){dropped=true;const response=await route.fetch();assert.equal(response.status(),200);await route.abort('failed');}
      else await route.continue();
    });
    await page.locator('#agent-request-consent').check();await page.locator('#agent-request-forward').click();
    await page.waitForFunction(()=>document.querySelector('#agent-request-view').textContent.includes('"status": "ADOPTED"'));
    const report=await control({op:'report',request_id:saved.request_id});
    assert.equal(report.status,'ADOPTED');assert.equal(report.result.result.state,'DRAFT');assert.equal(report.result.result.execution_enabled,false);
    assert.deepEqual(report.result,JSON.parse(await page.locator('#agent-request-view').textContent()).result);
    assert.equal(writes.length,1);assert.deepEqual(JSON.parse(writes[0]),{request_hash:saved.request_hash,expected_version:0});
    const actual=await control({op:'inspect'});assert.equal(actual.version,1);assert.equal(actual.drafts,1);
    assert.equal(actual.tasks+actual.sessions+actual.jobs,0);assert.equal(actual.other_version,0);
    await page.unroute('**/agent-requests/*/forward');
    const second=await control({op:'submit',goal_id:'browser_goal_b',key:'browser_original_b'});
    await page.locator('#agent-request-refresh').click();await page.waitForFunction(()=>document.querySelectorAll('#agent-request-list button').length===2);
    await page.locator(`[data-request-id="${saved.request_id}"]`).click();await page.waitForFunction(()=>document.querySelector('#agent-request-view').textContent.includes('browser_goal_a'));
    let releaseDetail,detailSeen;const seenDetail=new Promise(r=>detailSeen=r),waitDetail=new Promise(r=>releaseDetail=r);
    await page.route(`**/agent-requests/${second.request_id}`,async route=>{detailSeen();await waitDetail;await route.continue();});
    await page.locator(`[data-request-id="${second.request_id}"]`).click();await seenDetail;
    assert.equal(await page.locator('#agent-request-view').textContent(),'');assert.equal(await page.locator('#agent-request-private').isVisible(),false);
    releaseDetail();await page.waitForFunction(()=>document.querySelector('#agent-request-view').textContent.includes('browser_goal_b'));
    await page.unroute(`**/agent-requests/${second.request_id}`);
    let releaseSnapshot,snapshotSeen;const seenSnapshot=new Promise(r=>snapshotSeen=r),waitSnapshot=new Promise(r=>releaseSnapshot=r);
    await page.route('**/projects/project_other/snapshot',async route=>{snapshotSeen();await waitSnapshot;await route.continue();});
    await page.locator('#project-select').selectOption('project_other');await seenSnapshot;
    assert.equal(await page.locator('#agent-request-view').textContent(),'');assert.equal(await page.locator('#agent-request-private').isVisible(),false);
    releaseSnapshot();await page.waitForFunction(()=>document.querySelector('#project-title').textContent==='project_other');
    await page.unroute('**/projects/project_other/snapshot');
    await page.locator('#project-select').selectOption('project_fixture');await page.waitForFunction(()=>document.querySelector('#connection').textContent==='LIVE' && document.querySelector('#agent-request-list button'));
    await page.locator(`[data-request-id="${second.request_id}"]`).click();await page.waitForFunction(()=>document.querySelector('#agent-request-view').textContent.includes('browser_goal_b'));
    await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.locator('#logout').click();assert.equal(await page.locator('#agent-request-view').textContent(),'');assert.equal(await page.locator('#agent-request-list button').count(),0);
    assert.deepEqual(errors,[]);assert.equal(writes.length,1);
  } finally {
    if(browser)await browser.close();child.stdin.end('{"op":"stop"}\n');
    await new Promise(resolve=>{if(child.exitCode!==null)return resolve();const timer=setTimeout(()=>child.kill('SIGKILL'),5000);child.once('exit',()=>{clearTimeout(timer);resolve();});});
    await rm(root,{recursive:true,force:true});
  }
});
