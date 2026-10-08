import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, mkdir, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {chromium} from 'playwright-core';

const phrase = 'synthetic browser fixture passphrase';
const repo = resolve(new URL('..',import.meta.url).pathname);

test('real local Dashboard: durable SSE, offline recovery, identity clearing and native POST', {timeout:90000}, async () => {
  const fixture = await mkdtemp(resolve(tmpdir(),'rlflow-browser-'));
  const child = spawn(resolve(repo,'.venv/bin/python'),[resolve(repo,'web_checks/fixture_server.py'),fixture],
    {stdio:['pipe','pipe','pipe'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
  const messages = [], waiters = []; let stderr = '';
  child.stderr.on('data',value => { stderr += value; });
  createInterface({input:child.stdout}).on('line',line => { const value = JSON.parse(line); const waiter = waiters.shift(); if (waiter) waiter(value); else messages.push(value); });
  const next = () => messages.length ? Promise.resolve(messages.shift()) : new Promise((resolve,reject) => {
    const timer = setTimeout(() => reject(new Error(`fixture response timeout: ${stderr}`)),10000);
    waiters.push(value => {clearTimeout(timer);resolve(value);});
  });
  const control = async command => { child.stdin.write(JSON.stringify(command)+'\n'); return next(); };
  let browser;
  try {
    const {origin} = await next();
    browser = await chromium.launch({channel:'chrome',chromiumSandbox:true,headless:true,args:['--disable-gpu'],env:{PATH:'/usr/bin:/bin',LANG:'C.UTF-8'}});
    const context = await browser.newContext({viewport:{width:1440,height:1000}});
    await context.addInitScript(() => {
      window.observerRafCalls = 0;
      const original = window.requestAnimationFrame;
      // Playwright itself polls with rAF; count only calls originating in the app.
      window.requestAnimationFrame = callback => {
        if (new Error().stack.includes('/static/app.mjs')) window.observerRafCalls++;
        return original.call(window,callback);
      };
    });
    const page = await context.newPage(), errors = [];
    page.on('pageerror',error => errors.push(error.message));
    await page.goto(origin);
    const login = async name => {
      await page.locator('#principal').fill(name); await page.locator('#passphrase').fill(phrase);
      await page.locator('#login-form button').click();
    };
    await login('local');
    await page.waitForFunction(() => document.querySelector('#connection').textContent === 'LIVE');
    assert.equal(await page.locator('#task-total').textContent(),'1');
    assert.equal(await page.locator('.execution-node').getAttribute('data-state'),'STARTING');
    assert.match(await page.locator('#mode-note').textContent(),/FIXTURE/);
    assert.match(await page.locator('#objects').textContent(),/<img/);
    assert.equal(await page.evaluate(() => window.injected),undefined);
    assert.equal(await page.locator('#objects img').count(),0);
    const heartbeatTime = await page.locator('#sync-time').textContent();
    await page.waitForFunction(previous => document.querySelector('#sync-time').textContent !== previous,heartbeatTime);
    assert.equal(await page.locator('#task-total').textContent(),'1');
    assert.equal(await page.evaluate(() => window.observerRafCalls),0);
    await page.locator('.execution-node').focus(); await page.keyboard.press('Enter');
    assert.equal(await page.locator('#details').evaluate(node => node.open),true);
    await page.locator('#close-details').click();
    const first = await control({op:'task',id:'live_task'});
    await page.waitForFunction(at => document.querySelector('#cursor').textContent === at,first.head.cursor);
    assert.equal(await page.locator('#task-total').textContent(),'2');
    await page.locator('.event-row').first().click();
    await page.waitForFunction(() => document.querySelector('#details').open);
    assert.match(await page.locator('#detail-content').textContent(),/legacy.observed/);
    await page.locator('#close-details').click();
    await context.setOffline(true);
    await page.waitForFunction(() => document.querySelector('#connection').textContent === 'OFFLINE');
    await control({op:'task',id:'offline_task'});
    assert.equal(await page.locator('#task-total').textContent(),'2');
    await context.setOffline(false);
    await page.waitForFunction(() => document.querySelector('#task-total').textContent === '3',{},{timeout:15000});
    await page.waitForFunction(() => document.querySelector('#connection').textContent === 'LIVE');
    const burst = await control({op:'burst',count:205});
    await page.waitForFunction(at => document.querySelector('#cursor').textContent === at,burst.head.cursor,{timeout:20000});
    assert.equal(await page.locator('#task-total').textContent(),'208');
    assert.equal(await page.locator('.execution-node').count(),1);
    assert.ok(await page.locator('.event-row').count() <= 16);
    await page.locator('#events').evaluate(box => {box.scrollTop=640;});
    await page.waitForFunction(() => !!document.querySelector('[data-virtual-index="10"]'));
    const anchor = await page.locator('[data-virtual-index="10"]').getAttribute('data-event-id');
    const beforeTop = await page.locator(`[data-event-id="${anchor}"]`).evaluate(node => node.getBoundingClientRect().top-node.parentElement.getBoundingClientRect().top);
    const added = await control({op:'task',id:'while_reading'});
    await page.waitForFunction(at => document.querySelector('#cursor').textContent === at,added.head.cursor);
    const afterTop = await page.locator(`[data-event-id="${anchor}"]`).evaluate(node => node.getBoundingClientRect().top-node.parentElement.getBoundingClientRect().top);
    assert.ok(Math.abs(beforeTop-afterTop) < 1);
    assert.equal(await page.locator('#new-events').isVisible(),true);
    await page.locator('#events').focus(); await page.keyboard.press('End');
    await page.waitForFunction(() => document.activeElement.dataset.virtualIndex === '199');
    assert.ok(await page.locator('.event-row').count() <= 16);
    await page.keyboard.press('Enter'); await page.waitForFunction(() => document.querySelector('#details').open);
    await page.locator('#close-details').click();
    await page.locator('#new-events').click();
    await page.waitForFunction(() => document.querySelector('#events').scrollTop === 0);
    await page.locator('#events').focus(); await page.keyboard.press('Home');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.virtualIndex),'0');
    await page.locator('#event-filter').fill('NO_MATCHING_PUBLIC_EVENT');
    await page.waitForFunction(() => !document.querySelector('.event-row'));
    await page.locator('#event-filter').fill('');
    await page.waitForFunction(() => !!document.querySelector('.event-row'));
    assert.ok(await page.locator('.object-row').count() <= 50);
    assert.equal(await page.evaluate(() => localStorage.length+sessionStorage.length),0);
    await mkdir(resolve(repo,'web_checks/artifacts'),{recursive:true});
    await page.screenshot({path:resolve(repo,'web_checks/artifacts/dashboard-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.waitForFunction(() => {
      const box = document.querySelector('#events'), rect = box.getBoundingClientRect();
      return [...box.querySelectorAll('.event-row')].some(node => {
        const row = node.getBoundingClientRect(); return row.bottom > rect.top && row.top < rect.bottom;
      });
    },{},{timeout:3000});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({path:resolve(repo,'web_checks/artifacts/dashboard-mobile.png'),fullPage:true});
    await control({op:'expire'});
    await page.waitForFunction(() => !document.querySelector('#login-panel').hidden);
    await login('no_projects');
    await page.waitForFunction(() => document.querySelector('#error-banner').textContent.includes('没有可见项目'));
    for (const selector of ['.execution-node','.object-row','.event-row','#budgets > *']) assert.equal(await page.locator(selector).count(),0);
    assert.equal(await page.locator('#task-total').textContent(),'UNKNOWN');
    assert.equal(await page.locator('#detail-content').textContent(),'');
    await page.locator('#logout').click();
    assert.equal(await page.locator('#dashboard').evaluate(node => node.hidden),true);
    // An authenticated bootstrap stalled at projects must not revive the UI after logout.
    let releaseProjects, enteredProjects;
    const entered = new Promise(resolve => {enteredProjects=resolve;});
    const release = new Promise(resolve => {releaseProjects=resolve;});
    await page.route('**/api/v1/projects',async route => {enteredProjects();await release;await route.continue().catch(() => {});});
    await login('local'); await entered;
    await page.locator('#logout').dispatchEvent('click'); releaseProjects();
    await page.unroute('**/api/v1/projects');
    await page.waitForFunction(() => document.querySelector('#dashboard').hidden && !document.querySelector('#login-panel').hidden);
    assert.equal(await page.locator('.execution-node').count(),0);
    assert.deepEqual(errors,[]);
    await context.close();
    const noJS = await browser.newContext({javaScriptEnabled:false});
    const native = await noJS.newPage(); await native.goto(origin);
    await native.locator('#passphrase').fill(phrase);
    const submission = native.waitForRequest(request => request.url().includes('/api/v1/login'));
    await native.locator('#login-form button').click();
    const sent = await submission; assert.equal(sent.method(),'POST'); assert.ok(!sent.url().includes('passphrase'));
    assert.equal(new URL(sent.url()).search,'');
    await noJS.close();
  } finally {
    await browser?.close(); child.stdin.end(JSON.stringify({op:'stop'})+'\n');
    if (child.exitCode === null) await new Promise((resolve,reject) => {
      const timer = setTimeout(() => {child.kill('SIGTERM');reject(new Error('fixture did not stop'));},5000);
      child.once('exit',() => {clearTimeout(timer);resolve();});
    });
    await rm(fixture,{recursive:true});
  }
});
