import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';
const repo=resolve(new URL('..',import.meta.url).pathname);
test('Chrome same Auth two original projects: actual CPU384/engineering21, project clear and STOP isolation',{timeout:120000},async()=>{
  const root=await mkdtemp(resolve(tmpdir(),'rlflow-finite-host-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/finite_host_server.py'),root],{stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser,page;const messages=[],waiters=[];child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{try{const v=JSON.parse(line),w=waiters.shift();if(w)w(v);else messages.push(v);}catch{stderr+=line;}});
  const next=()=>messages.length?Promise.resolve(messages.shift()):new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(stderr)),45000);waiters.push(v=>{clearTimeout(timer);resolve(v);});});
  const control=async()=>{child.stdin.write('{"op":"inspect"}\n');return next();};
  try{
    const {origin,principal,phrase,projects}=await next();
    browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(origin);await page.locator('#principal').fill(principal);await page.locator('#passphrase').fill(phrase);await page.locator('#login-form button').click();
    await page.waitForFunction(()=>!document.querySelector('#cpu-unit-run').disabled);
    assert.equal(await page.locator('#project-select option').count(),2);
    await page.locator('#cpu-unit-run').click();
    await page.waitForFunction(()=>document.querySelector('#cpu-unit-detail').textContent.includes('EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'));
    await page.locator('#cpu-assessment-refresh').click();await page.waitForFunction(()=>document.querySelector('#cpu-assessment-list button'));
    await page.locator('#cpu-assessment-list button').first().click();await page.waitForFunction(()=>document.querySelector('#cpu-assessment-detail').textContent.includes('raw_samples'));
    const cpu=JSON.parse(await page.locator('#cpu-assessment-detail').textContent()).experiment;
    assert.equal(cpu.evidence.raw_samples.reduce((n,r)=>n+r.points.length,0),384);assert.equal(cpu.goal_completed,false);
    const before=await control();assert.equal(before.projects[1].cancelled,false);
    await page.locator('#cpu-unit-stop').click();await page.waitForFunction(()=>document.querySelector('#cpu-unit-stop-receipt').textContent.includes('STOP_INTENT_ACCEPTED'));
    const stopped=await control();assert.equal(stopped.projects[1].version,before.projects[1].version);assert.equal(stopped.projects[1].cancelled,false);
    await page.locator('#project-select').selectOption(projects[1]);
    await page.waitForFunction(()=>!document.querySelector('#engineering-unit-run').disabled);
    assert.equal(await page.locator('#cpu-assessment-detail').textContent(),'');assert.equal(await page.locator('#cpu-unit-stop-receipt').textContent(),'');
    await page.locator('#engineering-unit-run').click();await page.waitForFunction(()=>document.querySelector('#engineering-unit-detail').textContent.includes('MACHINE_ACCEPTED_PENDING_REVIEW'));
    await page.locator('#candidate-output-refresh').click();await page.waitForFunction(()=>document.querySelector('#candidate-output-list button'));
    await page.locator('#candidate-output-list button').first().click();await page.waitForFunction(()=>document.querySelector('#candidate-output-detail').textContent.includes('cpu_measurement_scope'));
    const engineering=JSON.parse(await page.locator('#candidate-output-detail').textContent()).candidate;
    assert.equal(engineering.machine_acceptance.derived.passed_cases,21);assert.equal(engineering.actual_cost_status,'UNKNOWN');assert.equal(engineering.goal_completed,false);
    assert.equal(Number.isSafeInteger(engineering.evidence.cpu_ns),true);assert.match(await page.locator('#candidate-output-note').textContent(),/不是账单/);
    const done=await control();assert.equal(done.launches,2);assert.equal(done.writes,1);assert.equal(done.occupied,0);assert.equal(done.projects[0].cancelled,true);assert.equal(done.projects[1].cancelled,false);
    await page.locator('#project-select').selectOption(projects[0]);await page.waitForFunction(()=>document.querySelector('#cpu-unit-detail').textContent.includes('EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'));
    assert.equal(await page.locator('#candidate-output-detail').textContent(),'');assert.equal(await page.locator('#engineering-unit-run-receipt').textContent(),'');
    assert.deepEqual(errors,[]);await page.locator('#logout').click();assert.equal(await page.locator('#cpu-unit-detail').textContent(),'');
  }catch(error){if(page)console.error('finite_host_diagnostic',await page.locator('#cpu-unit-note').textContent(),await page.locator('#engineering-unit-note').textContent(),await page.locator('#candidate-output-note').textContent());throw error;}
  finally{
    if(browser)await browser.close();child.stdin.write('{"op":"stop"}\n');child.stdin.end();
    const code=await new Promise((resolve,reject)=>{if(child.exitCode!==null)return resolve(child.exitCode);const timer=setTimeout(()=>{child.kill('SIGTERM');reject(new Error(stderr));},10000);child.once('exit',c=>{clearTimeout(timer);resolve(c);});});
    assert.equal(code,0,stderr);await rm(root,{recursive:true,force:true});
  }
});
