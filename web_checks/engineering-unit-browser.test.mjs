import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';
const repo=resolve(new URL('..',import.meta.url).pathname);
test('Chrome original engineering Run lost reply → manual receipt-only retry, single-write AST21 evidence, independent STOP and logout',{timeout:90000},async()=>{
  const root=await mkdtemp(resolve(tmpdir(),'rlflow-engineering-unit-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/engineering_unit_server.py'),root],{stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser,page;const messages=[],waiters=[];child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{try{const v=JSON.parse(line),w=waiters.shift();if(w)w(v);else messages.push(v);}catch{stderr+=line;}});
  const next=()=>messages.length?Promise.resolve(messages.shift()):new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(stderr)),30000);waiters.push(v=>{clearTimeout(timer);resolve(v);});});
  const control=async op=>{child.stdin.write(JSON.stringify({op})+'\n');return next();};
  try{
    const {origin,principal,phrase}=await next();
    browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    page=await browser.newPage();const errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.method()==='POST' && r.url().includes('/engineering-unit/commands'))writes.push({body:r.postData(),key:r.headers()['idempotency-key']});});
    await page.goto(origin);await page.locator('#principal').fill(principal);await page.locator('#passphrase').fill(phrase);await page.locator('#login-form button').click();
    await page.waitForFunction(()=>!document.querySelector('#engineering-unit-run').disabled);
    let release,held=false,first=true;const heldReply=new Promise(r=>release=r);
    await page.route('**/engineering-unit/commands',async route=>{
      if(first && JSON.parse(route.request().postData()).action==='START_FIXED_ENGINEERING'){
        first=false;const response=await route.fetch();assert.equal(response.status(),202);held=true;await heldReply;await route.abort('failed');
      }else await route.continue();
    });
    await page.locator('#engineering-unit-run').click();
    await page.waitForFunction(()=>document.querySelector('#engineering-unit-detail').textContent.includes('MACHINE_ACCEPTED_PENDING_REVIEW'));
    assert.equal(held,true);assert.equal(await page.locator('#engineering-unit-stop').isEnabled(),true);
    await page.locator('#engineering-unit-stop').click();await page.waitForFunction(()=>document.querySelector('#engineering-unit-stop-receipt').textContent.includes('STOP_INTENT_ACCEPTED'));
    release();await page.waitForFunction(()=>!document.querySelector('#engineering-unit-run-retry').hidden);
    const before=await control('inspect');assert.equal(before.launches,1);assert.equal(before.writes,1);assert.equal(before.occupied,0);assert.equal(before.fds_closed,true);assert.equal(before.returncode,0);
    await page.locator('#engineering-unit-run-retry').click();await page.waitForFunction(()=>document.querySelector('#engineering-unit-run-receipt').textContent.includes('HANDOFF_UNKNOWN'));
    await page.locator('#candidate-output-refresh').click();await page.waitForFunction(()=>document.querySelector('#candidate-output-list button'));
    await page.locator('#candidate-output-list button').first().click();await page.waitForFunction(()=>document.querySelector('#candidate-output-detail').textContent.includes('machine_acceptance'));
    const evidence=JSON.parse(await page.locator('#candidate-output-detail').textContent()).candidate;
    assert.equal(evidence.machine_acceptance.derived.passed_cases,21);assert.equal(evidence.goal_completed,false);assert.equal(evidence.independent_review_status,'NOT_PERFORMED');
    await page.locator('#engineering-unit-stop-retry').click();await page.waitForFunction(()=>document.querySelector('#engineering-unit-stop-receipt').textContent.includes('"duplicate": true'));
    const after=await control('inspect');assert.equal(after.version,before.version);assert.equal(after.launches,1);assert.equal(after.writes,1);
    assert.equal(writes.length,4);assert.deepEqual(writes[0],writes[2]);assert.deepEqual(writes[1],writes[3]);assert.equal('expected_state_version' in JSON.parse(writes[1].body),false);
    await control('close_owner');await page.locator('#engineering-unit-refresh').click();await page.waitForFunction(()=>document.querySelector('#engineering-unit-detail').textContent.includes('"original_owner_available": false'));
    assert.equal(await page.locator('#engineering-unit-stop').isEnabled(),false);assert.deepEqual(errors,[]);
    await page.locator('#logout').click();assert.equal(await page.locator('#engineering-unit-detail').textContent(),'');assert.equal(await page.locator('#engineering-unit-run-receipt').textContent(),'');assert.equal(await page.locator('#engineering-unit-stop-receipt').textContent(),'');
  }catch(error){
    if(page)console.error('readonly_candidate_diagnostic',await page.locator('#candidate-output-note').textContent());
    throw error;
  }finally{
    if(browser)await browser.close();child.stdin.write('{"op":"stop"}\n');child.stdin.end();
    const code=await new Promise((resolve,reject)=>{if(child.exitCode!==null)return resolve(child.exitCode);const timer=setTimeout(()=>{child.kill('SIGTERM');reject(new Error(stderr));},10000);child.once('exit',c=>{clearTimeout(timer);resolve(c);});});
    assert.equal(code,0,stderr);await rm(root,{recursive:true,force:true});
  }
});
