import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';
const repo=resolve(new URL('..',import.meta.url).pathname);
test('real CPU evidence → original appraisal → viewer Chrome, durable refresh and owner closure',{timeout:90000},async()=>{
  const root=await mkdtemp(resolve(tmpdir(),'rlflow-cpu-assessment-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/cpu_trial_server.py'),root],{stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser;const messages=[],waiters=[];child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{try{const v=JSON.parse(line),w=waiters.shift();if(w)w(v);else messages.push(v);}catch{stderr+=line;}});
  const next=()=>messages.length?Promise.resolve(messages.shift()):new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(stderr)),25000);waiters.push(v=>{clearTimeout(timer);resolve(v);});});
  const control=async op=>{child.stdin.write(JSON.stringify({op})+'\n');return next();};
  try{
    const {origin,principal,phrase}=await next();
    browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    const page=await browser.newPage(),errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()!=='GET' && !r.url().endsWith('/login') && !r.url().endsWith('/logout'))writes.push(r.url());});
    await page.goto(origin);await page.locator('#principal').fill(principal);await page.locator('#passphrase').fill(phrase);await page.locator('#login-form button').click();
    await page.waitForFunction(()=>document.querySelector('#cpu-assessment-list button'));
    assert.match(await page.locator('#cpu-assessment-list').textContent(),/SUCCEEDED \/ VALID \/ SUPPORTED/);
    await page.locator('#cpu-assessment-list button').click();await page.waitForFunction(()=>document.querySelector('#cpu-assessment-detail').textContent.includes('raw_samples'));
    const detail=JSON.parse(await page.locator('#cpu-assessment-detail').textContent());
    assert.equal(detail.experiment.evidence.raw_samples.reduce((n,r)=>n+r.points.length,0),384);
    assert.deepEqual(detail.experiment.evidence.inside_counts,[96,101,104]);assert.equal(detail.experiment.evidence.mean_absolute_error,0.08821911547006896);
    assert.equal(detail.experiment.goal_completed,false);assert.equal(detail.experiment.assessment.independent_review_status,'NOT_PERFORMED');
    const before=await control('inspect');assert.equal(before.version,before.initial_version);assert.equal(before.occupied,0);
    const updated=await control('append_assessment');assert.equal(updated.version,before.version+1);
    await page.waitForFunction(()=>document.querySelectorAll('#cpu-assessment-list button').length===2);
    await page.waitForFunction(v=>{const text=document.querySelector('#cpu-assessment-detail').textContent;return text && JSON.parse(text).as_of_state_version===v;},updated.version);
    await control('close_owner');await page.locator('#cpu-assessment-refresh').click();await page.waitForFunction(()=>document.querySelector('#cpu-assessment-detail').textContent.includes('raw_samples'));
    assert.equal((await control('inspect')).version,updated.version);assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
    await page.locator('#logout').click();assert.equal(await page.locator('#cpu-assessment-detail').textContent(),'');assert.equal(await page.locator('#cpu-assessment-list').textContent(),'');
  }finally{
    if(browser)await browser.close();child.stdin.write('{"op":"stop"}\n');child.stdin.end();
    const code=await new Promise((resolve,reject)=>{if(child.exitCode!==null)return resolve(child.exitCode);const timer=setTimeout(()=>{child.kill('SIGTERM');reject(new Error(stderr));},10000);child.once('exit',c=>{clearTimeout(timer);resolve(c);});});
    assert.equal(code,0,stderr);await rm(root,{recursive:true,force:true});
  }
});
