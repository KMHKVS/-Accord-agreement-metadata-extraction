// Uses the real running app and readers. Model output is mocked, never a live accuracy test.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

async function main() {
  fs.mkdirSync('output', { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_CHANNEL ? {channel: process.env.BROWSER_CHANNEL} : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    // Keep tests independent of any real server credentials or default provider.
    await page.route('**/api/config', async (route) => {
      const response = await route.fetch();
      const data = await response.json();
      data.configured = false; data.provider = 'openai'; data.model = 'gpt-4.1-mini';
      for (const provider of Object.values(data.providers)) provider.configured = false;
      data.providers.openai.model = 'gpt-4.1-mini';
      data.providers.groq.model = 'qwen/qwen3.8-27b';
      await route.fulfill({response, json:data});
    });
    await page.goto(process.env.APP_URL || 'http://127.0.0.1:8000');
    await page.getByText('Connect AI', {exact:true}).waitFor();
    await page.screenshot({ path: 'output/ui-desktop.png', fullPage: true });
    await page.locator('#file-input').setInputFiles(path.resolve('data/train/50070534-RENTAL-AGREEMENT.docx'));
    assert.equal(await page.locator('#file-count').textContent(), '1');
    await page.getByRole('tab', {name:'Source document'}).click();
    await page.locator('#view-source pre').waitFor();
    assert.match(await page.locator('#view-source pre').textContent(), /JohnsonRavikumar/);
    await page.getByRole('button', {name:'Extract details'}).click();
    assert.equal(await page.locator('#settings-dialog').isVisible(), true);
    await page.locator('#api-key').fill('test-only-key');
    await page.getByRole('button', {name:'Save settings'}).click();
    assert.equal(await page.locator('#api-key').inputValue(), '');
    let calls = 0;
    let failNext = false;
    let expectedKey = 'test-only-key', expectedProvider = 'openai';
    await page.route('**/api/extract', async (route) => {
      calls++;
      assert.equal(route.request().headers()['x-api-key'], expectedKey);
      assert.ok(route.request().postData().includes('name="provider"\r\n\r\n' + expectedProvider));
      assert.match(route.request().postData(), /Content-Disposition: form-data/);
      if (failNext) {
        failNext = false;
        return route.fulfill({status:429, contentType:'application/json', body:JSON.stringify({detail:'Test usage limit. Try again later.'})});
      }
      const field = (value) => ({value, status: value === null ? 'missing' : 'found', evidence:value === null ? null : 'Evidence for UI test only.', explanation:'Mock response — browser test only.'});
      const result = {
        document_type:'Rental agreement (test response)', summary:'A mock extraction used only to exercise the UI.', currency:'INR',
        agreement_value:field('10000'), agreement_start_date:field('01.04.2010'), agreement_end_date:field('30.03.2011'),
        renewal_notice_days:field('90'), party_one:field('<script>alert("unsafe")</script>'), party_two:field(null),
        warnings:['Test warning: review this result.'],
      };
      await route.fulfill({contentType:'application/json', body:JSON.stringify({filename:'test.docx', provider:expectedProvider, model:'test-model', result})});
    });
    await page.getByRole('tab', {name:'Extracted details'}).click();
    await page.getByRole('button', {name:'Extract details'}).click();
    await page.getByText('Rental agreement (test response)', {exact:true}).waitFor();
    assert.equal(await page.locator('.field-card').count(), 6);
    assert.equal(await page.locator('#results script').count(), 0);
    assert.match(await page.locator('#results').textContent(), /<script>/);
    await page.locator('.field-card summary').first().click();
    assert.equal(await page.locator('.field-card blockquote').first().isVisible(), true);
    await page.screenshot({path:'output/ui-results.png', fullPage:true});
    await page.getByRole('tab', {name:'JSON',exact:true}).click();
    assert.match(await page.locator('#view-json pre').textContent(), /test-model/);
    await page.getByRole('button', {name:'↓ Export',exact:true}).click();
    const jsonDownload = page.waitForEvent('download');
    await page.getByRole('button', {name:'↓ This document · JSON'}).click();
    const json = await jsonDownload;
    assert.match(json.suggestedFilename(), /\.json$/);
    JSON.parse(fs.readFileSync(await json.path(), 'utf8'));
    // A second, image-only document must use the actual preview reader.
    await page.locator('#file-input').setInputFiles(path.resolve('data/test/24158401-Rental-Agreement.png'));
    await page.getByRole('button', {name:'Select 24158401-Rental-Agreement.png'}).click();
    await page.getByRole('tab', {name:'Source document'}).click();
    await page.locator('#view-source img').first().waitFor();
    await page.getByRole('tab', {name:'Extracted details'}).click();
    failNext = true;
    await page.getByRole('button', {name:'Extract details'}).click();
    await page.getByText('Test usage limit. Try again later.', {exact:true}).waitFor();
    await page.getByRole('button', {name:'Extract details'}).click();
    await page.getByText('Rental agreement (test response)', {exact:true}).waitFor();
    await page.getByRole('button', {name:'↓ Export',exact:true}).click();
    const csvDownload = page.waitForEvent('download');
    await page.getByRole('button', {name:'↓ All completed · CSV'}).click();
    const csv = fs.readFileSync(await (await csvDownload).path(), 'utf8');
    assert.equal(csv.split('\r\n').length, 3);
    assert.equal(calls, 3);
    // Responsive layout and basic overflow checks.
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'output/ui-mobile.png',fullPage:true});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await page.getByRole('button', {name:'Clear',exact:true}).click();
    assert.equal(await page.locator('#file-count').textContent(), '0');
    await page.locator('#file-input').setInputFiles([
      {name:'first.txt', mimeType:'text/plain', buffer:Buffer.from('First unseen agreement')},
      {name:'second.txt', mimeType:'text/plain', buffer:Buffer.from('Second unseen agreement')},
    ]);
    await page.getByRole('button', {name:'Extract 2 documents'}).click();
    await page.waitForFunction(() => document.querySelectorAll('.file-state.done').length === 2);
    assert.equal(calls, 5);
    await page.locator('#settings-open').click();
    await page.locator('#provider-input').selectOption('groq');
    assert.equal(await page.locator('#api-key').inputValue(), '');
    assert.equal(await page.locator('#model-input').inputValue(), 'qwen/qwen3.8-27b');
    await page.screenshot({path:'output/ui-groq-settings.png', fullPage:true});
    await page.locator('#api-key').fill('sk-wrong-provider-test-only');
    await page.getByRole('button', {name:'Save settings'}).click();
    assert.equal(await page.locator('#settings-dialog').isVisible(), true);
    expectedKey = 'gsk_test_only'; expectedProvider = 'groq';
    await page.locator('#api-key').fill(expectedKey);
    await page.getByRole('button', {name:'Save settings'}).click();
    assert.equal(await page.locator('#privacy-provider').textContent(), 'Groq');
    await page.getByRole('button', {name:'Extract again'}).click();
    await page.waitForFunction(() => document.querySelector('#extract-all').textContent !== 'Extracting documents…');
    assert.equal(calls, 6);
    await page.getByRole('tab', {name:'JSON',exact:true}).click();
    assert.match(await page.locator('#view-json pre').textContent(), /"provider": "groq"/);
    await page.locator('#settings-open').click();
    await page.locator('#provider-input').selectOption('openai');
    assert.equal(await page.locator('#api-key').inputValue(), '');
    assert.equal(await page.locator('#model-input').inputValue(), 'gpt-4.1-mini');
    await page.locator('#settings-close').click();
    await page.reload();
    await page.getByText('Connect AI', {exact:true}).waitFor();
    assert.deepEqual(errors, []);
    console.log('Browser checks passed: upload, real previews, settings, extraction UI, safe text rendering, error recovery, JSON/CSV export, mobile layout, session reset. Model responses were mocked.');
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
