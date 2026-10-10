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
  const root=await mkdtemp(resolve(tmpdir(),'rlflow-accounting-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/finite_host_server.py'),root,mode],{stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser,page;const messages=[],waiters=[];child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{try{const value=JSON.parse(line),wait=waiters.shift();if(wait)wait(value);else messages.push(value);}catch{stderr+=line;}});
  const next=()=>messages.length?Promise.resolve(messages.shift()):new Promise((accept,reject)=>{const timer=setTimeout(()=>reject(new Error(stderr || 'private fixture deadline')),60000);waiters.push(v=>{clearTimeout(timer);accept(v);});});
  const control=async op=>{child.stdin.write(JSON.stringify({op})+'\n');return next();};
  const close=async()=>{
    if(browser)await browser.close();child.stdin.write('{"op":"stop"}\n');child.stdin.end();
    const code=await new Promise((accept,reject)=>{if(child.exitCode!==null)return accept(child.exitCode);const timer=setTimeout(()=>{child.kill('SIGTERM');reject(new Error(stderr));},15000);child.once('exit',c=>{clearTimeout(timer);accept(c);});});
    assert.equal(code,0,stderr); // Retain actual fixture roots, no removal.
  };
  try{
    const ready=await next();browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(ready.origin);await page.locator('#principal').fill(ready.principal);await page.locator('#passphrase').fill(ready.phrase);await page.locator('#login-form button').click();
    await page.waitForFunction(()=>document.querySelector('#finite-accounting-detail').textContent.includes('ORIGINAL_FINITE_ACCOUNTING'));
    return {page,root,control,close,errors,projects:ready.projects};
  }catch(e){await close();throw e;}
}
async function read(p){
  await p.waitForFunction(()=>!document.querySelector('#finite-accounting-refresh').disabled);
  await p.locator('#finite-accounting-refresh').click();
  await p.waitForFunction(()=>!document.querySelector('#finite-accounting-refresh').disabled && document.querySelector('#finite-accounting-detail').textContent.includes('ORIGINAL_FINITE_ACCOUNTING'));
  return JSON.parse(await p.locator('#finite-accounting-detail').textContent());
}
test('Chrome original ledger and shared Pool from actual CPU/engineering execution, independent STOP and late read isolation',{timeout:150000},async()=>{
  const f=await fixture('accounting'),p=f.page;let posts=0;
  p.on('request',r=>{if(r.url().endsWith('/finite-accounting'))assert.equal(r.method(),'GET');if(r.method()==='POST' && /\/(cpu|engineering)-unit\/commands/.test(r.url()))posts++;});
  try{
    const initial=await read(p);assert.equal(initial.pool.occupied,2);assert.equal(initial.pool.project_occupied,1);assert.equal(initial.budget.balances.experiment_starts.reserved,'1');
    const baseline=await f.control('inspect');await read(p);assert.deepEqual(await f.control('inspect'),baseline);
    await p.locator('#cpu-unit-run').click();await p.waitForFunction(()=>document.querySelector('#cpu-unit-detail').textContent.includes('EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'));
    const cpu=await read(p),cpuProof=await f.control('inspect');assert.equal(cpu.pool.occupied,1);assert.equal(cpu.pool.project_occupied,0);
    assert.equal(cpu.budget.balances.experiment_starts.consumed,'1');assert.equal(cpu.budget.balances.experiment_starts.reserved,'0');assert.equal(cpu.budget.balances.experiment_starts.unknown_exposure,'0');
    assert.deepEqual(cpu.budget.balances.experiment_starts,Object.fromEntries(Object.entries(cpuProof.projects[0].experiment_balance).map(([k,v])=>[k,String(v)])));
    await p.locator('#project-select').selectOption(f.projects[1]);await p.waitForFunction(()=>!document.querySelector('#engineering-unit-run').disabled);
    const engineeringBefore=await read(p);assert.equal(engineeringBefore.pool.project_occupied,1);assert.equal(engineeringBefore.pool.occupied,1);assert.equal(engineeringBefore.budget.balances.experiment_starts.limit,'0');
    await p.locator('#engineering-unit-run').click();await p.waitForFunction(()=>document.querySelector('#engineering-unit-detail').textContent.includes('MACHINE_ACCEPTED_PENDING_REVIEW'));
    const engineering=await read(p);assert.equal(engineering.pool.occupied,0);assert.equal(engineering.pool.project_occupied,0);
    assert.equal(engineering.budget.actual_cost_status,'UNKNOWN');assert.equal(engineering.cross_database_atomic,false);
    // New UI's unavailable response clears numbers, never substitutes zero.
    let fail=true;await p.route('**/finite-accounting',async route=>{if(fail){fail=false;await route.fulfill({status:503,contentType:'application/json',body:'{}'});}else await route.continue();});
    await p.locator('#finite-accounting-refresh').click();await p.waitForFunction(()=>document.querySelector('#finite-accounting-note').textContent.startsWith('UNKNOWN'));
    assert.equal(await p.locator('#finite-accounting-detail').textContent(),'');await read(p);
    await p.locator('#project-select').selectOption(f.projects[0]);await read(p);
    await f.control('hold_accounting');await p.locator('#finite-accounting-refresh').click();
    let held;for(let i=0;i<30;i++){held=await f.control('inspect');if(held.held)break;await new Promise(r=>setTimeout(r,20));}assert.equal(held.held,true);
    assert.equal(await p.locator('#finite-stop-stop').isEnabled(),true);await p.locator('#finite-stop-stop').click();
    await p.waitForFunction(()=>document.querySelector('#finite-stop-receipt').textContent.includes('ORIGINAL_SCOPES_STOPPED_AS_OF_RETURN'));
    await p.locator('#logout').click();await f.control('release');
    assert.equal(await p.locator('#finite-accounting-detail').textContent(),'');
    const final=await f.control('inspect');assert.equal(final.launches,2);assert.equal(final.writes,1);assert.equal(final.occupied,0);assert.equal(posts,2);assert.deepEqual(f.errors,[]);
    console.log('finite_accounting_browser',JSON.stringify({root:f.root,launches:final.launches,writes:final.writes,occupied:final.occupied,cpu_budget:cpu.budget.balances.experiment_starts,cpu_version:cpu.as_of_state_version,pool_version:cpu.pool.as_of_pool_version}));
  }catch(e){console.error('accounting_browser_note',await p.locator('#finite-accounting-note').textContent());throw e;}
  finally{await f.close();}
});
test('Chrome real Popen-return loss exposes reserved UNKNOWN after original STOP, not zero/refund',{timeout:100000},async()=>{
  const f=await fixture('unknown-start'),p=f.page;
  try{
    const initial=await read(p);assert.equal(initial.pool.occupied,2);await p.locator('#cpu-unit-run').click();
    await p.waitForFunction(()=>!document.querySelector('#cpu-unit-reconcile').hidden);
    const unknown=await read(p);assert.equal(unknown.pool.project_occupied,1);assert.equal(unknown.pool.occupied,2);
    assert.equal(unknown.budget.reservation_status,'UNKNOWN');assert.equal(unknown.budget.balances.experiment_starts.unknown_exposure,'1');assert.equal(unknown.budget.balances.experiment_starts.reserved,'1');
    await p.locator('#finite-stop-stop').click();await p.waitForFunction(()=>document.querySelector('#finite-stop-receipt').textContent.includes('PARTIAL_OR_UNKNOWN'));
    const stopped=await read(p),proof=await f.control('inspect');assert.equal(stopped.pool.occupied,1);assert.equal(stopped.pool.project_occupied,1);
    assert.deepEqual(stopped.budget.balances.experiment_starts,Object.fromEntries(Object.entries(proof.projects[0].experiment_balance).map(([k,v])=>[k,String(v)])));
    assert.equal(stopped.budget.balances.experiment_starts.consumed,'0');assert.equal(stopped.budget.balances.experiment_starts.unknown_exposure,'1');assert.equal(proof.launches,1);assert.equal(proof.occupied,1);
    assert.match(await p.locator('#finite-accounting-note').textContent(),/实际费用 UNKNOWN/);await p.locator('#logout').click();assert.equal(await p.locator('#finite-accounting-detail').textContent(),'');assert.deepEqual(f.errors,[]);
    console.log('finite_accounting_unknown',JSON.stringify({root:f.root,launches:proof.launches,occupied:stopped.pool.occupied,balance:stopped.budget.balances.experiment_starts}));
  }finally{await f.close();}
});
