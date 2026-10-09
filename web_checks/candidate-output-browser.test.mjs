import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';
const repo=resolve(new URL('..',import.meta.url).pathname);
test('actual engineer output → cold viewer Chrome; durable refresh, owner closed, logout',{timeout:90000},async()=>{
  const root=await mkdtemp(resolve(tmpdir(),'rlflow-candidate-output-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/candidate_output_server.py'),root],{stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser;const messages=[],waiters=[];child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{try{const v=JSON.parse(line),w=waiters.shift();if(w)w(v);else messages.push(v);}catch{stderr+=line;}});
  const next=()=>messages.length?Promise.resolve(messages.shift()):new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(stderr)),30000);waiters.push(v=>{clearTimeout(timer);resolve(v);});});
  const control=async op=>{child.stdin.write(JSON.stringify({op})+'\n');return next();};
  try{
    const {origin,principal,phrase}=await next();
    browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    const page=await browser.newPage(),errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()!=='GET' && !r.url().endsWith('/login') && !r.url().endsWith('/logout'))writes.push(r.url());});
    await page.goto(origin);await page.locator('#principal').fill(principal);await page.locator('#passphrase').fill(phrase);await page.locator('#login-form button').click();
    await page.waitForFunction(()=>document.querySelector('#candidate-output-list button'));
    assert.match(await page.locator('#candidate-output-list').textContent(),/baseline失败 2 → 实际通过 3/);
    await page.locator('#candidate-output-list button').click();await page.waitForFunction(()=>document.querySelector('#candidate-output-detail').textContent.includes('actual_tests'));
    const detail=JSON.parse(await page.locator('#candidate-output-detail').textContent()),row=detail.candidate;
    assert.deepEqual(row.evidence.actual_tests.map(r=>r.actual),[5,-2,0]);assert.notEqual(row.before_sha256,row.after_sha256);assert.notEqual(row.base_tree_sha256,row.output_tree_sha256);
    assert.equal(row.current_activation,'HISTORICAL_AUDIT_ONLY');assert.equal(row.resource_release_status,'NOT_OBSERVED');assert.equal(row.goal_completed,false);assert.equal(row.independent_review_status,'NOT_PERFORMED');
    assert.equal(row.machine_acceptance.status,'MACHINE_ACCEPTED_PENDING_REVIEW');assert.equal(row.machine_acceptance.derived.passed_cases,21);assert.equal(row.machine_acceptance.derived.actual_tests.length,21);assert.equal(row.machine_acceptance.independent_review_status,'NOT_PERFORMED');assert.deepEqual(row.machine_acceptance.condition_coverage,[]);
    const before=await control('inspect');assert.equal(before.version,before.initial_version);assert.equal(before.occupied,0);assert.equal(before.candidate_write_closed,true);
    const updated=await control('append_readonly_event');assert.equal(updated.version,before.version+1);
    await page.waitForFunction(v=>{const text=document.querySelector('#candidate-output-detail').textContent;return text && JSON.parse(text).as_of_state_version===v;},updated.version);
    await control('close_owner');await page.locator('#candidate-output-refresh').click();await page.waitForFunction(()=>document.querySelector('#candidate-output-detail').textContent.includes('actual_tests'));
    assert.equal((await control('inspect')).version,updated.version);assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
    await page.locator('#logout').click();assert.equal(await page.locator('#candidate-output-detail').textContent(),'');assert.equal(await page.locator('#candidate-output-list').textContent(),'');
  }finally{
    if(browser)await browser.close();child.stdin.write('{"op":"stop"}\n');child.stdin.end();
    const code=await new Promise((resolve,reject)=>{if(child.exitCode!==null)return resolve(child.exitCode);const timer=setTimeout(()=>{child.kill('SIGTERM');reject(new Error(stderr));},10000);child.once('exit',c=>{clearTimeout(timer);resolve(c);});});
    assert.equal(code,0,stderr);await rm(root,{recursive:true,force:true});
  }
});
