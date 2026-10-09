import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';
const repo=resolve(new URL('..',import.meta.url).pathname);
test('actual viewer SSE updates selected original timeline after offline START/ACK and STOP; heartbeat never refreshes or writes',{timeout:90000},async()=>{
  const fixture=await mkdtemp(resolve(tmpdir(),'rlflow-fixture-live-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/fixture_runtime_server.py'),fixture],{stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser,diagnostic;const messages=[],waiters=[];child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{try{const v=JSON.parse(line),waiter=waiters.shift();if(waiter)waiter(v);else messages.push(v);}catch{stderr+=line;}});
  const next=()=>messages.length?Promise.resolve(messages.shift()):new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(`fixture timeout: ${stderr}`)),20000);waiters.push(v=>{clearTimeout(timer);resolve(v);});});
  const control=async op=>{child.stdin.write(JSON.stringify({op})+'\n');return next();};
  try{
    const {origin,principal,phrase}=await next();
    browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    const operatorContext=await browser.newContext(),viewerContext=await browser.newContext();
    const operator=await operatorContext.newPage(),viewer=await viewerContext.newPage(),errors=[],viewerWrites=[],pageReads=[];
    diagnostic=async()=>({actual:await control('inspect'),errors,pages:await Promise.all([operator,viewer].map(page=>page.evaluate(()=>Object.fromEntries(['connection','login-error','error-banner','fixture-note','fixture-live','fixture-detail','fixture-receipt'].map(id=>[id,document.getElementById(id)?.textContent])))))});
    for(const page of [operator,viewer])page.on('pageerror',e=>errors.push(e.message));
    viewer.on('request',r=>{if(r.url().includes('/fixture-tasks/')){if(r.method()==='POST')viewerWrites.push(r.url());}if(r.url().includes('/fixture-tasks?'))pageReads.push(Date.now());});
    const login=async(page,name)=>{await page.goto(origin);await page.locator('#principal').fill(name);await page.locator('#passphrase').fill(phrase);await page.locator('#login-form button').click();try{await page.waitForFunction(()=>document.querySelector('#fixture-list button') && !document.querySelector('#fixture-list button').disabled);await page.locator('#fixture-list button').click();await page.waitForFunction(()=>document.querySelector('#fixture-timeline li'));}catch(e){throw new Error(`${e.message}; diagnostic ${JSON.stringify({errors,dom:await page.evaluate(()=>Object.fromEntries(['connection','login-error','error-banner','fixture-note','fixture-live','fixture-list'].map(id=>[id,document.getElementById(id)?.textContent]))),stderr})}`);}};
    await login(operator,principal);await login(viewer,'fixture_viewer');
    assert.equal(await viewer.locator('#fixture-start').isDisabled(),true);assert.equal(await viewer.locator('#fixture-timeline li').count(),1);
    const initialDetail=await viewer.locator('#fixture-detail').textContent();await viewerContext.setOffline(true);await viewer.waitForFunction(()=>document.querySelector('#fixture-live').textContent.includes('OFFLINE'));
    await operator.locator('#fixture-start').click();await operator.waitForFunction(()=>document.querySelector('#fixture-detail').textContent.includes('STARTED_AS_OBSERVED'));
    const started=await control('inspect');assert.equal(started.phase,'STARTED_AS_OBSERVED');assert.equal(await viewer.locator('#fixture-detail').textContent(),initialDetail);
    await viewerContext.setOffline(false);await viewer.waitForFunction(()=>document.querySelector('#fixture-detail').textContent.includes('STARTED_AS_OBSERVED'));
    assert.equal(await viewer.locator('#fixture-timeline li').count(),5);assert.match(await viewer.locator('#fixture-detail').textContent(),/"current_execution_status": "UNKNOWN"/);
    await operator.waitForFunction(()=>!document.querySelector('#fixture-stop').disabled);await operator.locator('#fixture-stop').click();
    await viewer.waitForFunction(()=>document.querySelector('#fixture-timeline li:last-child')?.textContent.includes('FIXTURE_SCOPE_STOPPED'));
    assert.equal(await viewer.locator('#fixture-timeline li').count(),7);const stopped=await control('inspect');assert.equal(stopped.process_reaped,true);assert.equal(stopped.occupied,0);
    assert.match(await viewer.locator('#fixture-detail').textContent(),/"resource_release_status": "NOT_OBSERVED"/);
    await viewer.waitForFunction(()=>document.querySelector('#connection').textContent==='LIVE' && !document.querySelector('#fixture-live').textContent.includes('STALE'));
    const reads=pageReads.length,sync=await viewer.locator('#sync-time').textContent();
    await viewer.waitForFunction(old=>document.querySelector('#sync-time').textContent!==old,sync);assert.equal(pageReads.length,reads);assert.equal(viewerWrites.length,0);
    // Automatic list batches are bounded by one second, not by number of events.
    for(let i=2;i<pageReads.length;i++)assert.ok(pageReads[i]-pageReads[i-1]>=850,JSON.stringify(pageReads));
    assert.deepEqual(errors,[]);await viewer.locator('#logout').click();assert.equal(await viewer.locator('#fixture-timeline li').count(),0);assert.equal(await viewer.locator('#fixture-detail').textContent(),'');
  }catch(e){throw new Error(`${e.stack}\n${JSON.stringify(diagnostic?await diagnostic():{stderr})}`);}finally{
    if(browser)await browser.close();child.stdin.write('{"op":"stop"}\n');child.stdin.end();
    const code=await new Promise((resolve,reject)=>{if(child.exitCode!==null)return resolve(child.exitCode);const timer=setTimeout(()=>{child.kill('SIGTERM');reject(new Error(`fixture failed to close: ${stderr}`));},10000);child.once('exit',code=>{clearTimeout(timer);resolve(code);});});
    assert.equal(code,0,stderr);await rm(fixture,{recursive:true,force:true});
  }
});
