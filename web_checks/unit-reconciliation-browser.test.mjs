import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';
const repo=resolve(new URL('..',import.meta.url).pathname);
async function fixture(mode){
  const root=await mkdtemp(resolve(tmpdir(),'rlflow-reconcile-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/finite_host_server.py'),root,mode],{stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser,page;const messages=[],waiters=[];child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{try{const value=JSON.parse(line),wait=waiters.shift();if(wait)wait(value);else messages.push(value);}catch{stderr+=line;}});
  const next=()=>messages.length?Promise.resolve(messages.shift()):new Promise((accept,reject)=>{const timer=setTimeout(()=>reject(new Error(stderr || 'private fixture response deadline')),60000);waiters.push(v=>{clearTimeout(timer);accept(v);});});
  const control=async op=>{child.stdin.write(JSON.stringify({op})+'\n');return next();};
  const close=async()=>{
    if(browser)await browser.close();child.stdin.write('{"op":"stop"}\n');child.stdin.end();
    const code=await new Promise((accept,reject)=>{if(child.exitCode!==null)return accept(child.exitCode);const timer=setTimeout(()=>{child.kill('SIGTERM');reject(new Error(stderr));},15000);child.once('exit',c=>{clearTimeout(timer);accept(c);});});
    assert.equal(code,0,stderr); // Retain actual fixture roots/evidence, do not erase them.
  };
  try{
    const ready=await next();browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(ready.origin);await page.locator('#principal').fill(ready.principal);await page.locator('#passphrase').fill(ready.phrase);await page.locator('#login-form button').click();
    await page.waitForFunction(()=>!document.querySelector('#cpu-unit-run').disabled);
    return {page,root,control,close,errors,projects:ready.projects};
  }catch(e){await close();throw e;}
}
const recovered=async(page,kind,status)=>page.waitForFunction(([kind,status])=>document.querySelector('#'+kind+'-reconcile-detail').textContent.includes(status),[kind,status]);

test('Chrome actual missing decision/lost commit → explicit original recovery, lost reply retry and independent STOP',{timeout:150000},async()=>{
  const f=await fixture('machine-failures'),p=f.page,requests=[];
  p.on('request',r=>{if(r.method()==='POST' && /\/(cpu|engineering)-unit\/commands/.test(r.url()))requests.push({url:r.url(),body:r.postData(),key:r.headers()['idempotency-key']});});
  let last;
  try{
    let wrongStatus=true;
    await p.route('**/cpu-unit/commands',async route=>{
      if(wrongStatus && JSON.parse(route.request().postData()).action==='START_FIXED_CPU'){
        wrongStatus=false;const response=await route.fetch();assert.equal(response.status(),202);await route.fulfill({response,status:200});
      }else await route.continue();
    });
    await p.locator('#cpu-unit-run').click();await p.waitForFunction(()=>!document.querySelector('#cpu-unit-run-retry').hidden);
    assert.equal(await p.locator('#cpu-unit-reconcile').isVisible(),false);
    const failed=await f.control('inspect');assert.equal(failed.launches,1);assert.equal(failed.projects[0].machine_facts,0);
    await p.locator('#cpu-unit-run-retry').click();await p.waitForFunction(()=>!document.querySelector('#cpu-unit-reconcile').hidden && !document.querySelector('#cpu-unit-reconcile').disabled);
    const accepted=await f.control('inspect');assert.equal(accepted.projects[0].version,failed.projects[0].version);assert.equal(accepted.reconciliations.length,0);
    let lose=true;
    await p.route('**/cpu-unit/commands/*/reconcile',async route=>{
      if(lose){lose=false;const response=await route.fetch();assert.equal(response.status(),200);await route.abort('failed');}else await route.continue();
    });
    await p.locator('#cpu-unit-reconcile').click();await p.waitForFunction(()=>document.querySelector('#cpu-unit-reconcile-note').textContent.includes('恢复结果 UNKNOWN'));
    assert.equal(await p.locator('#cpu-unit-reconcile-detail').textContent(),'');
    await p.locator('#cpu-unit-reconcile').click();await recovered(p,'cpu-unit','EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW');
    const cpu=JSON.parse(await p.locator('#cpu-unit-reconcile-detail').textContent()),after=await f.control('inspect');
    assert.equal(cpu.result.goal_completed,false);assert.equal(after.launches,1);assert.equal(after.projects[0].machine_facts,1);
    assert.equal(after.projects[0].version,accepted.projects[0].version+1);assert.equal(after.projects[1].version,accepted.projects[1].version);
    assert.deepEqual(after.reconciliations.map(r=>r.new_events),[1,0]);assert.deepEqual(after.reconciliations[0].result_fact,after.reconciliations[1].result_fact);
    assert.match(await p.locator('#cpu-unit-reconcile-note').textContent(),/预算未读取/);
    const cpuRequests=requests.filter(r=>r.url.includes('/cpu-unit/commands'));
    assert.equal(cpuRequests.length,4);for(const r of cpuRequests){assert.equal(r.body,cpuRequests[0].body);assert.equal(r.key,cpuRequests[0].key);}
    await p.locator('#project-select').selectOption(f.projects[1]);await p.waitForFunction(()=>!document.querySelector('#engineering-unit-run').disabled);
    assert.equal(await p.locator('#cpu-unit-reconcile-detail').textContent(),'');
    await p.locator('#engineering-unit-run').click();await p.waitForFunction(()=>!document.querySelector('#engineering-unit-reconcile').hidden && !document.querySelector('#engineering-unit-reconcile').disabled);
    const beforeEngineering=await f.control('inspect');assert.equal(beforeEngineering.projects[1].machine_facts,1);
    await p.locator('#engineering-unit-reconcile').click();await recovered(p,'engineering-unit','MACHINE_ACCEPTED_PENDING_REVIEW');
    const engineering=await f.control('inspect');assert.equal(engineering.projects[1].version,beforeEngineering.projects[1].version);assert.equal(engineering.launches,2);assert.equal(engineering.writes,1);
    assert.equal(engineering.reconciliations.at(-1).new_events,0);
    await f.control('hold_engineering');await p.locator('#engineering-unit-reconcile').click();
    let held;for(let i=0;i<30;i++){held=await f.control('inspect');if(held.held)break;await new Promise(r=>setTimeout(r,20));}assert.equal(held.held,true);
    assert.equal(await p.locator('#engineering-unit-stop').isEnabled(),true);
    await p.locator('#engineering-unit-stop').click();await p.waitForFunction(()=>document.querySelector('#engineering-unit-stop-receipt').textContent.includes('STOP_INTENT_ACCEPTED'));
    await p.locator('#project-select').selectOption(f.projects[0]);await f.control('release');
    await p.waitForFunction(()=>document.querySelector('#cpu-unit-detail').textContent.includes('EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'));
    assert.equal(await p.locator('#engineering-unit-reconcile-detail').textContent(),'');assert.equal(await p.locator('#cpu-unit-reconcile').isVisible(),false);
    last=await f.control('inspect');assert.equal(last.launches,2);assert.equal(last.writes,1);assert.equal(last.G_count,2);assert.equal(last.collect_count,2);assert.equal(last.occupied,0);
    assert(last.reconciliations.every(r=>r.launch_delta===0 && r.write_delta===0 && r.G_delta===0 && r.collect_delta===0));
    await p.locator('#project-select').selectOption(f.projects[1]);await f.control('close_engineering');await p.locator('#engineering-unit-refresh').click();
    await p.waitForFunction(()=>document.querySelector('#engineering-unit-detail').textContent.includes('"original_owner_available": false'));
    assert.equal(await p.locator('#engineering-unit-reconcile').isVisible(),false);
    await p.locator('#logout').click();assert.equal(await p.locator('#engineering-unit-reconcile-detail').textContent(),'');assert.deepEqual(f.errors,[]);
    console.log('original_reconcile_browser',JSON.stringify({root:f.root,launches:last.launches,writes:last.writes,G:last.G_count,collect:last.collect_count,occupied:last.occupied,reconciliations:last.reconciliations}));
  }catch(e){console.error('reconcile_browser_diagnostic',await p.locator('#cpu-unit-note').textContent(),await p.locator('#cpu-unit-reconcile-note').textContent(),await p.locator('#engineering-unit-reconcile-note').textContent());throw e;}
  finally{await f.close();}
});

test('Chrome real Popen-return loss stays UNKNOWN after explicit recovery and STOP; no budget refund',{timeout:100000},async()=>{
  const f=await fixture('unknown-start'),p=f.page;
  try{
    const initial=await f.control('inspect');assert.equal(initial.occupied,2);
    await p.locator('#cpu-unit-run').click();await p.waitForFunction(()=>!document.querySelector('#cpu-unit-reconcile').hidden && !document.querySelector('#cpu-unit-reconcile').disabled);
    const before=await f.control('inspect');assert.equal(before.launches,1);assert.equal(before.occupied,2);assert.equal(before.projects[0].experiment_balance.unknown_exposure,1);
    await p.locator('#cpu-unit-reconcile').click();await recovered(p,'cpu-unit','UNKNOWN_RESULT_UNAVAILABLE');
    const value=JSON.parse(await p.locator('#cpu-unit-reconcile-detail').textContent());assert.equal(value.result_fact,null);assert.equal(value.result.goal_completed,false);
    const after=await f.control('inspect');assert.equal(after.launches,1);assert.equal(after.G_count,0);assert.equal(after.collect_count,0);assert.equal(after.occupied,2);
    assert.equal(after.projects[0].version,before.projects[0].version);assert.deepEqual(after.projects[0].experiment_balance,before.projects[0].experiment_balance);
    assert.equal(after.projects[1].version,initial.projects[1].version);assert.match(await p.locator('#cpu-unit-reconcile-note').textContent(),/未证明未知曝露退还/);
    await p.locator('#finite-stop-stop').click();
    await p.waitForFunction(()=>document.querySelector('#finite-stop-receipt').textContent.includes('UNKNOWN'));
    const stopped=await f.control('inspect');assert.equal(stopped.occupied,1);assert.equal(stopped.projects[0].experiment_balance.unknown_exposure,1);
    assert.equal(stopped.projects[0].experiment_balance.consumed,0);assert.equal(stopped.launches,1);
    assert.deepEqual(f.errors,[]);await p.locator('#logout').click();assert.equal(await p.locator('#cpu-unit-reconcile-detail').textContent(),'');
    console.log('unknown_reconcile_browser',JSON.stringify({root:f.root,launches:stopped.launches,occupied:stopped.occupied,balance:stopped.projects[0].experiment_balance}));
  }finally{await f.close();}
});
