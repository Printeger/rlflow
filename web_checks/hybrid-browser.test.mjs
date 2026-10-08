import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';
const repo=resolve(new URL('..',import.meta.url).pathname);
const phrase='synthetic HTTP control fixture passphrase';

test('owned real browser Hybrid roles, exact human confirmation/revoke, uncertain original-key retry and cleanup',{timeout:90000},async()=>{
  const fixture=await mkdtemp(resolve(tmpdir(),'rlflow-hybrid-browser-'));
  const child=spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/hybrid_fixture_server.py'),fixture],
    {stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  let stderr='',browser;const messages=[],waiters=[];
  child.stderr.on('data',v=>stderr+=v);
  createInterface({input:child.stdout}).on('line',line=>{const v=JSON.parse(line),waiter=waiters.shift();if(waiter)waiter(v);else messages.push(v);});
  const next=()=>messages.length?Promise.resolve(messages.shift()):new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error(`fixture response timeout: ${stderr}`)),10000);
    waiters.push(v=>{clearTimeout(timer);resolve(v);});
  });
  const control=async op=>{child.stdin.write(JSON.stringify({op})+'\n');return next();};
  try {
    const {origin,proposal}=await next();
    proposal.objective+='<img src=x onerror="window.hybridInjected=1">';
    browser=await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    const context=await browser.newContext({viewport:{width:1440,height:1100}}),page=await context.newPage(),errors=[],writes=[];let confirmationRequests=0;
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.method()==='POST' && r.url().endsWith('/commands'))writes.push({body:r.postData(),key:r.headers()['idempotency-key']});if(r.url().endsWith('/approval-confirmations'))confirmationRequests++;});
    await page.goto(origin);
    const login=async principal=>{
      await page.locator('#principal').fill(principal);await page.locator('#passphrase').fill(phrase);await page.locator('#login-form button').click();
      await page.waitForFunction(()=>document.querySelector('#connection').textContent==='LIVE');
      await page.waitForFunction(()=>document.querySelector('#goal-note').textContent.includes('HEAD_ONLY'));
    };
    await login('viewer');assert.equal(await page.locator('#goal-editor').isVisible(),false);
    assert.equal(await page.locator('#observer-tag').textContent(),'READ-ONLY OBSERVER');
    assert.equal(await page.locator('#goal-private').isVisible(),false);await page.locator('#logout').click();
    await login('operator');
    assert.equal(await page.locator('#observer-tag').textContent(),'NON-EXECUTING FACT CONTROL');
    for(const suffix of ['"allowed_tools":[],"allowed_tools":["hidden"]','"budget":{},"budget":{"wall_seconds":99}',
      '"budget":{"model_input_tokens":9007199254740993}','"budget":{"wall_seconds":1e309}']){
      await page.locator('#goal-json').fill(JSON.stringify(proposal).slice(0,-1)+','+suffix+'}');await page.locator('#goal-submit').click();
      assert.match(await page.locator('#goal-note').textContent(),/未提交/);assert.equal(writes.length,0);
      assert.equal((await control('inspect')).version,0);
    }
    await page.locator('#goal-json').fill(JSON.stringify(proposal));await page.locator('#goal-submit').click();
    await page.waitForFunction(()=>document.querySelector('#goal-receipt').textContent.includes('DRAFT'));
    await page.waitForFunction(()=>!!document.querySelector('#goal-list .goal-row'));
    await page.locator('.goal-row').focus();await page.keyboard.press('Enter');await page.waitForFunction(()=>document.querySelector('#goal-review').textContent.includes('ORIGINAL_EVENT_VERIFIED'));
    assert.equal(await page.locator('#goal-prepare').isDisabled(),true);
    assert.match(await page.locator('#goal-review').textContent(),/"execution_enabled": false/);
    assert.equal(await page.locator('#goal-review img').count(),0);assert.equal(await page.evaluate(()=>window.hybridInjected),undefined);
    await page.locator('#logout').click();assert.equal(await page.locator('#goal-review').textContent(),'');
    assert.equal(await page.locator('#goal-json').inputValue(),'');
    await login('viewer');assert.equal(await page.locator('.goal-row').isDisabled(),true);
    assert.equal(await page.locator('#goal-private').isVisible(),false);assert.equal(await page.locator('#goal-review').textContent(),'');
    await page.locator('#logout').click();
    await login('approver');assert.equal(await page.locator('#goal-editor').isVisible(),false);
    await page.locator('.goal-row').click();await page.waitForFunction(()=>document.querySelector('#goal-review').textContent.includes('ORIGINAL_EVENT_VERIFIED'));
    await page.locator('#goal-prepare').click();await page.waitForFunction(()=>document.querySelector('#goal-confirmation').textContent.includes('view_hash'));
    assert.equal(await page.locator('#goal-approve').isDisabled(),true);
    await page.locator('#goal-ttl').fill('360');assert.equal(await page.locator('#goal-confirmation').textContent(),'');
    assert.equal(await page.locator('#goal-approve').isDisabled(),true);
    await page.locator('#goal-prepare').click();await page.waitForFunction(()=>document.querySelector('#goal-confirmation').textContent.includes('view_hash'));
    await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.setViewportSize({width:1440,height:1100});
    assert.match(await page.locator('#goal-confirmation').textContent(),/ACTUAL_OS_AND_RESOURCE_ENFORCEMENT_NOT_VERIFIED/);
    const shown=JSON.parse(await page.locator('#goal-confirmation').textContent());
    // The backend actually commits; browser delivery is then deliberately lost.
    let dropped=false;
    await page.route('**/commands',async route=>{
      if(!dropped){dropped=true;const result=await route.fetch();assert.equal(result.status(),202);await route.abort('failed');}
      else await route.continue();
    });
    await page.locator('#goal-consent').check();await page.locator('#goal-approve').click();
    await page.waitForFunction(()=>!document.querySelector('#goal-retry').hidden);
    assert.deepEqual(JSON.parse(writes.at(-1).body).parameters.confirmation,shown.confirmation);
    const committed=await control('inspect');assert.equal(committed.approvals,1);assert.equal(committed.sessions,0);assert.equal(committed.tasks,0);
    await page.locator('#goal-retry').click();await page.waitForFunction(()=>document.querySelector('#goal-receipt').textContent.includes('LEASE_VALIDATION_PENDING'));
    assert.equal(writes.at(-1).key,writes.at(-2).key);assert.equal(writes.at(-1).body,writes.at(-2).body);
    assert.match(await page.locator('#goal-receipt').textContent(),/"duplicate": true/);
    await page.unroute('**/commands');
    await page.waitForFunction(()=>document.querySelector('#goal-list').textContent.includes('LEASE_VALIDATION_PENDING'));
    await page.locator('.goal-row').click();await page.waitForFunction(()=>!document.querySelector('#goal-revoke').disabled);
    await page.locator('#goal-reason').fill('explicit isolated browser revoke');await page.locator('#goal-revoke').click();
    await page.waitForFunction(()=>document.querySelector('#goal-receipt').textContent.includes('REVOKED'));
    const revoked=await control('inspect');assert.equal(revoked.approvals,1);assert.equal(revoked.revocations,1);assert.equal(revoked.sessions,0);
    await page.waitForFunction(()=>document.querySelector('#goal-list').textContent.includes('REVOKED'));
    await page.locator('.goal-row').click();await page.waitForFunction(()=>document.querySelector('#goal-review').textContent.includes('REVOKED'));
    assert.equal(await page.locator('#goal-revoke').isDisabled(),true);
    // Held old identity request must not expire the freshly logged-in identity.
    let releaseOld,seenOld;const oldSeen=new Promise(r=>seenOld=r),oldRelease=new Promise(r=>releaseOld=r);let held=false;
    await page.route('**/review',async route=>{
      if(!held){held=true;seenOld();await oldRelease;await route.fulfill({status:401,contentType:'application/json',body:'{"detail":"old session expired"}'});}
      else await route.continue();
    });
    await page.locator('.goal-row').click();await oldSeen;
    await page.locator('#logout').click();await login('operator');await page.locator('.goal-row').click();
    await page.waitForFunction(()=>document.querySelector('#goal-review').textContent.includes('REVOKED'));
    const freshBody=await page.locator('#goal-review').textContent(),oldResponse=page.waitForResponse(r=>r.url().endsWith('/review') && r.status()===401);releaseOld();await oldResponse;
    await page.waitForTimeout(150);
    assert.equal(await page.locator('#login-panel').isVisible(),false);assert.equal(await page.locator('#goal-review').textContent(),freshBody);
    assert.equal(await page.locator('#connection').textContent(),'LIVE');await page.unroute('**/review');
    const unsafe=await control('unsafe_goal');await page.locator('#logout').click();await login('approver');
    const previousWrites=writes.length,previousPreparations=confirmationRequests;
    await page.locator(`[data-goal-ref="${unsafe.unsafe_ref}"]`).click();
    await page.waitForFunction(()=>document.querySelector('#goal-note').textContent.includes('inconsistent'));
    assert.equal(await page.locator('#goal-review').textContent(),'');assert.equal(await page.locator('#goal-prepare').isDisabled(),true);
    assert.equal(await page.locator('#goal-approve').isDisabled(),true);assert.equal(writes.length,previousWrites);assert.equal(confirmationRequests,previousPreparations);
    assert.equal((await control('inspect')).approvals,1);
    await control('expire');await page.locator('#goal-refresh').click();
    await page.waitForFunction(()=>document.querySelector('#goal-review').textContent==='');
    assert.equal(await page.locator('#goal-confirmation').textContent(),'');assert.equal(await page.locator('#goal-private').isVisible(),false);
    assert.deepEqual(errors,[]);
    console.log('HYBRID_BROWSER_FIXTURE: actual draft+approval+revocation, original-key retry after committed response loss; no tasks/sessions/execution');
  } finally {
    if(browser)await browser.close();child.stdin.end(JSON.stringify({op:'stop'})+'\n');
    const exited=await new Promise(resolve=>{if(child.exitCode!==null)return resolve(true);const timer=setTimeout(()=>resolve(false),5000);child.once('exit',()=>{clearTimeout(timer);resolve(true);});});
    if(!exited){child.kill('SIGTERM');await new Promise(resolve=>child.once('exit',resolve));}
    await rm(fixture,{recursive:true,force:true});
    assert.equal(exited,true,`fixture normal shutdown timed out: ${stderr}`);assert.equal(child.exitCode,0,stderr);
  }
});
