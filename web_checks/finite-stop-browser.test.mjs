import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';
const repo=resolve(new URL('..',import.meta.url).pathname);
test('Chrome human original whole-scope STOP, per-project receipts, project/logout private clear',{timeout:90000},async()=>{
  const root=await mkdtemp(resolve(tmpdir(),'rlflow-finite-stop-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/finite_host_server.py'),root],{stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser,page;const messages=[],waiters=[];child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{try{const v=JSON.parse(line),w=waiters.shift();if(w)w(v);else messages.push(v);}catch{stderr+=line;}});
  const next=()=>messages.length?Promise.resolve(messages.shift()):new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error(stderr)),45000);waiters.push(v=>{clearTimeout(timer);resolve(v);});});
  try{
    const {origin,principal,phrase,projects}=await next();browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    page=await browser.newPage();const errors=[],posts=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/finite-host/commands'))posts.push(r);});
    await page.goto(origin);await page.locator('#principal').fill(principal);await page.locator('#passphrase').fill(phrase);await page.locator('#login-form button').click();
    await page.waitForFunction(()=>!document.querySelector('#finite-stop-stop').disabled);assert.equal(posts.length,0);
    const profile=JSON.parse(await page.locator('#finite-stop-scope').textContent());assert.equal(profile.items.length,2);
    await page.locator('#finite-stop-stop').click();await page.waitForFunction(()=>document.querySelector('#finite-stop-receipt').textContent.includes('ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'));
    const receipt=JSON.parse(await page.locator('#finite-stop-receipt').textContent());assert.equal(receipt.items.length,2);assert.equal(receipt.durable_aggregate_receipt,false);assert.equal(receipt.goal_completed,false);
    assert.equal(receipt.items.every(r=>r.intent.recorded_phase==='STOP_INTENT_ACCEPTED'&&r.cleanup_status==='ORIGINAL_SCOPE_STOPPED'),true);
    child.stdin.write('{"op":"inspect"}\n');const actual=await next();assert.equal(actual.occupied,0);assert.equal(actual.launches,0);assert.equal(actual.writes,0);assert.equal(actual.projects.every(p=>p.cancelled),true);assert.equal(posts.length,1);
    await page.locator('#project-select').selectOption(projects[1]);await page.waitForFunction(()=>document.querySelector('#finite-stop-scope').textContent.includes('ORIGINAL_FIXED_BOUND_UNITS_ONLY'));assert.equal(await page.locator('#finite-stop-receipt').textContent(),'');assert.equal(posts.length,1);
    await page.locator('#logout').click();assert.equal(await page.locator('#finite-stop-scope').textContent(),'');assert.equal(await page.locator('#finite-stop-receipt').textContent(),'');assert.deepEqual(errors,[]);
  }catch(error){if(page)console.error('finite_stop_diagnostic',await page.locator('#finite-stop-note').textContent());throw error;}
  finally{if(browser)await browser.close();child.stdin.write('{"op":"stop"}\n');child.stdin.end();const code=await new Promise((resolve,reject)=>{if(child.exitCode!==null)return resolve(child.exitCode);const timer=setTimeout(()=>{child.kill('SIGTERM');reject(Error(stderr));},10000);child.once('exit',c=>{clearTimeout(timer);resolve(c);});});assert.equal(code,0,stderr);await rm(root,{recursive:true,force:true});}
});
