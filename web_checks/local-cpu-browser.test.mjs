import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';
const repo=resolve(new URL('..',import.meta.url).pathname);
test('actual authenticated Dashboard local research machine result and historical charge; no fixed controls',{timeout:90000},async()=>{
  const fixture=await mkdtemp(resolve(tmpdir(),'rlflow-local-cpu-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/local_cpu_server.py'),fixture],{stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser;const messages=[],waiters=[];child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{try{const v=JSON.parse(line);if(!v.browser_ready && !v.fixture_inspection)return;const waiter=waiters.shift();if(waiter)waiter(v);else messages.push(v);}catch{stderr+=line;}});
  const next=()=>messages.length?Promise.resolve(messages.shift()):new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(`local fixture timeout: ${stderr}`)),25000);waiters.push(v=>{clearTimeout(timer);resolve(v);});});
  const control=async op=>{child.stdin.write(JSON.stringify({op})+'\n');return next();};
  try{
    const {origin,principal,phrase}=await next();
    browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[],writes=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST' && r.url().includes('/fixture-tasks/'))writes.push(r.url());});
    await page.goto(origin);await page.locator('#principal').fill(principal);await page.locator('#passphrase').fill(phrase);await page.locator('#login-form button').click();
    await page.waitForFunction(()=>document.querySelector('#fixture-list button'));
    await page.locator('#fixture-list button').click();await page.waitForFunction(()=>document.querySelector('#fixture-detail').textContent.includes('LOCAL_CONFIGURED_CPU'));
    assert.equal(await page.locator('#fixture-start').isDisabled(),true);assert.equal(await page.locator('#fixture-stop').isDisabled(),true);
    const stopped=await control('run');assert.equal(stopped.occupied,0);assert.equal(stopped.view.recorded_settled_usage.experiment_starts,1);
    await page.waitForFunction(()=>document.querySelector('#fixture-detail').textContent.includes('"machine_acceptance_status": "PASS"'));
    const displayed=JSON.parse(await page.locator('#fixture-detail').textContent());
    assert.deepEqual(displayed,stopped.view);assert.equal(displayed.task.current_execution_status,'UNKNOWN');
    assert.equal(displayed.task.independent_review_status,'NOT_PROVEN');assert.equal(displayed.task.condition_evidence,false);
    assert.equal(JSON.parse(displayed.configured_result.outputs.stdout.text).median,4);
    assert.equal(await page.locator('#fixture-start').isDisabled(),true);assert.equal(await page.locator('#fixture-stop').isDisabled(),true);
    const inspected=await control('inspect');assert.equal(inspected.version,stopped.version);assert.deepEqual(writes,[]);
    await page.locator('#logout').click();assert.equal(await page.locator('#fixture-detail').textContent(),'');assert.deepEqual(errors,[]);
  }finally{
    if(browser)await browser.close();child.stdin.write('{"op":"stop"}\n');child.stdin.end();
    const code=await new Promise((resolve,reject)=>{if(child.exitCode!==null)return resolve(child.exitCode);const timer=setTimeout(()=>{child.kill('SIGTERM');reject(new Error(`fixture cleanup timeout: ${stderr}`));},10000);child.once('exit',code=>{clearTimeout(timer);resolve(code);});});
    assert.equal(code,0,stderr);await rm(fixture,{recursive:true,force:true});
  }
});
