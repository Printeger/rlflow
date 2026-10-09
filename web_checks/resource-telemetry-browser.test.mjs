import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';
const repo=resolve(new URL('..',import.meta.url).pathname);
test('actual OS sample → existing SSE/Chrome → closed original owner UNKNOWN; other project unaffected',{timeout:90000},async()=>{
  const root=await mkdtemp(resolve(tmpdir(),'rlflow-resource-telemetry-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/resource_telemetry_server.py'),root],{stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser;const messages=[],waiters=[];child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{try{const v=JSON.parse(line),w=waiters.shift();if(w)w(v);else messages.push(v);}catch{stderr+=line;}});
  const next=()=>messages.length?Promise.resolve(messages.shift()):new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error(stderr)),35000);waiters.push(v=>{clearTimeout(timer);resolve(v);});});
  const control=async op=>{child.stdin.write(JSON.stringify({op})+'\n');return next();};
  try{
    const {origin,principal,phrase,projects}=await next();
    browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    const page=await browser.newPage(),errors=[],writes=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()!=='GET' && !r.url().endsWith('/login') && !r.url().endsWith('/logout'))writes.push(r.url());});
    await page.goto(origin);await page.locator('#principal').fill(principal);await page.locator('#passphrase').fill(phrase);await page.locator('#login-form button').click();
    await page.waitForFunction(()=>document.querySelector('#resource-memory').textContent.includes('GiB'));
    assert.match(await page.locator('#resource-workers').textContent(),/FIXED_WORKER_PROCESS.*UNKNOWN/);
    const before=await control('inspect');assert.deepEqual(before.versions,before.initial_versions);
    const updated=await control('sample');
    assert.deepEqual(updated.versions,before.versions);
    await page.waitForFunction(id=>document.querySelector('#resource-note').textContent.includes(id),updated.samples[0].sample_id);
    const closed=await control('close_owner');
    assert.ok(closed.versions[0]>before.versions[0]); // Explicit original shutdown writes STOP, unlike GET/sample.
    assert.equal(closed.versions[1],before.versions[1]);
    await page.waitForFunction(()=>document.querySelector('#resource-memory').textContent==='UNKNOWN');
    assert.match(await page.locator('#resource-note').textContent(),new RegExp(closed.samples[0].sample_id));
    assert.equal(closed.samples[1].host.memory.status,'KNOWN');
    const select=page.locator('#project-select');await select.selectOption(projects[1]);
    await page.waitForFunction(()=>document.querySelector('#resource-memory').textContent.includes('GiB'));
    await page.reload();await page.waitForFunction(()=>document.querySelector('#resource-note').textContent.includes('CORE_OS_SAMPLE'));
    assert.equal(await page.locator('#resource-memory').textContent(),'UNKNOWN');
    await page.locator('#project-select').selectOption(projects[1]);
    await page.waitForFunction(()=>document.querySelector('#resource-memory').textContent.includes('GiB'));
    const after=await control('inspect');assert.deepEqual(after.versions,closed.versions);assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
    await page.locator('#logout').click();assert.equal(await page.locator('#resource-workers').textContent(),'');assert.equal(await page.locator('#resource-memory').textContent(),'UNKNOWN');
  }finally{
    if(browser)await browser.close();child.stdin.write('{"op":"stop"}\n');child.stdin.end();
    const code=await new Promise((resolve,reject)=>{if(child.exitCode!==null)return resolve(child.exitCode);const timer=setTimeout(()=>{child.kill('SIGTERM');reject(new Error(stderr));},10000);child.once('exit',c=>{clearTimeout(timer);resolve(c);});});
    assert.equal(code,0,stderr);await rm(root,{recursive:true,force:true});
  }
});
