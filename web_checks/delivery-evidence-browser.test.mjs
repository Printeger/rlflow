import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';
const repo=resolve(new URL('..',import.meta.url).pathname);
test('actual Chrome original CPU384/AST21 -> real condition denominators -> missing Review and private clear',{timeout:120000},async()=>{
  const root=await mkdtemp(resolve(tmpdir(),'rlflow-delivery-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/finite_host_server.py'),root],{stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser,page;const messages=[],waiters=[];child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{try{const v=JSON.parse(line),w=waiters.shift();if(w)w(v);else messages.push(v);}catch{stderr+=line;}});
  const next=()=>messages.length?Promise.resolve(messages.shift()):new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error(stderr)),45000);waiters.push(v=>{clearTimeout(timer);resolve(v);});});
  try{
    const {origin,principal,phrase,projects}=await next();browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    page=await browser.newPage();const errors=[],deliveryGets=[],deliveryPosts=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().includes('/delivery-evidence/'))(r.method()==='GET'?deliveryGets:deliveryPosts).push(r);});
    await page.goto(origin);await page.locator('#principal').fill(principal);await page.locator('#passphrase').fill(phrase);await page.locator('#login-form button').click();
    for(const [i,prefix,unit,terminal] of [[0,'cpu-assessment','cpu-unit','EXPERIMENT_MACHINE_VERIFIED_PENDING_REVIEW'],[1,'candidate-output','engineering-unit','MACHINE_ACCEPTED_PENDING_REVIEW']]){
      if(i)await page.locator('#project-select').selectOption(projects[i]);
      await page.waitForFunction(u=>!document.querySelector(`#${u}-run`).disabled,unit);await page.locator(`#${unit}-run`).click();
      await page.waitForFunction(({u,t})=>document.querySelector(`#${u}-detail`).textContent.includes(t),{u:unit,t:terminal});
      await page.locator(`#${prefix}-refresh`).click();await page.waitForFunction(p=>document.querySelector(`#${p}-list button`),prefix);await page.locator(`#${prefix}-list button`).first().click();
      await page.waitForFunction(p=>!document.querySelector(`#${p}-delivery`).disabled,prefix);assert.equal(deliveryGets.length,i);
      await page.locator(`#${prefix}-delivery`).click();await page.waitForFunction(p=>document.querySelector(`#${p}-conditions`).textContent.includes('BLOCKED_MISSING_EVIDENCE'),prefix);
      const body=JSON.parse(await page.locator(`#${prefix}-conditions`).textContent());assert.ok(body.required_count>0);assert.equal(body.required_count,body.conditions.filter(c=>c.required).length);assert.equal(body.required_satisfied_count,0);
      assert.equal(body.machine_context.raw_item_count,i?3:384);assert.equal(body.machine_context.machine_case_count,i?21:0);assert.equal(body.independent_review_status,'NOT_PERFORMED');assert.equal(body.goal_completed,false);assert.equal(body.conditions.every(c=>c.status==='UNASSESSED'&&c.condition_evidence_refs.length===0),true);
      if(i)assert.equal(await page.locator('#cpu-assessment-conditions').textContent(),'');
    }
    child.stdin.write('{"op":"inspect"}\n');const actual=await next();assert.equal(actual.launches,2);assert.equal(actual.writes,1);assert.equal(actual.occupied,0);assert.equal(deliveryGets.length,2);assert.equal(deliveryPosts.length,0);
    await page.locator('#logout').click();assert.equal(await page.locator('#candidate-output-conditions').textContent(),'');assert.deepEqual(errors,[]);
    console.log('actual_delivery_UI',JSON.stringify({cpu_raw:384,engineering_AST:21,original_denominators:true,Review:'NOT_PERFORMED',Goal:false,extra_workers:0,extra_writes:0}));
  }catch(error){if(page)console.error('delivery_diagnostic',await page.locator('#cpu-assessment-conditions').textContent(),await page.locator('#candidate-output-conditions').textContent());throw error;}
  finally{if(browser)await browser.close();child.stdin.write('{"op":"stop"}\n');child.stdin.end();const code=await new Promise((resolve,reject)=>{if(child.exitCode!==null)return resolve(child.exitCode);const timer=setTimeout(()=>{child.kill('SIGTERM');reject(Error(stderr));},10000);child.once('exit',c=>{clearTimeout(timer);resolve(c);});});assert.equal(code,0,stderr);await rm(root,{recursive:true,force:true});}
});
