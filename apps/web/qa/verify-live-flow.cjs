const { chromium } = require('../node_modules/@playwright/test');
const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; const requests = []; const previews = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.url().endsWith('/api/query')) requests.push(request.postDataJSON()); });
  page.on('response', response => { if (response.url().includes('/api/preview/')) previews.push(response.status()); });
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });
  const cases = [
    { files: ['before'], modalities: ['optical'], question: 'Describe the land cover', route: 'single_image' },
    { files: ['after', 'before'], modalities: ['optical', 'optical'], question: 'What changed?', route: 'change' },
    { files: ['sar', 'before'], modalities: ['sar', 'optical'], question: 'Compare the optical and SAR images', route: 'optical_sar' },
    { files: ['before', 'mismatch'], modalities: ['optical', 'optical'], question: 'What changed?', route: 'reject' },
  ];
  const outcomes = [];
  for (const scenario of cases) {
    await page.getByRole('button', { name: 'New investigation', exact: true }).click();
    await page.getByRole('region', { name: 'Attach GeoTIFF scenes' }).waitFor();
    await page.getByLabel('Choose GeoTIFF files').setInputFiles(scenario.files.map(name => path.join(__dirname, 'fixtures', name + '.tif')));
    for (let i = 0; i < scenario.files.length; i++) {
      await page.getByLabel('Modality', { exact: true }).nth(i).selectOption(scenario.modalities[i]);
      await page.getByLabel('Acquisition date', { exact: true }).nth(i).fill(scenario.files[i] === 'before' ? '2024-06-12' : '2024-06-24');
    }
    await page.getByRole('button', { name: 'Validate and attach', exact: true }).click();
    await page.getByRole('region', { name: 'Attach GeoTIFF scenes' }).waitFor({ state: 'hidden', timeout: 20000 });
    await page.getByLabel('Question about your satellite scenes').fill(scenario.question);
    const responseWait = page.waitForResponse(response => response.url().endsWith('/api/query'));
    await page.getByRole('button', { name: 'Ask SatQuery', exact: true }).click();
    const data = await (await responseWait).json();
    assert.equal(data.task, scenario.route);
    await page.getByRole('button', { name: 'Download JSON', exact: true }).waitFor();
    assert.equal(data.overlay.type, 'none');
    assert.deepEqual(data.facts, {});
    if (scenario.route !== 'reject') assert.equal(data.receipt.trace.at(-1).status, 'stub');
    else { await page.getByText('These inputs cannot be analysed', { exact: true }).waitFor(); assert.equal(await page.locator('.scene-viewer__overlay').count(), 0); }
    const downloadWait = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export receipt', exact: true }).click();
    const download = await downloadWait; const destination = path.join(__dirname, `receipt-${scenario.route}.json`);
    await download.saveAs(destination);
    const receipt = JSON.parse(fs.readFileSync(destination, 'utf8'));
    assert.equal(receipt.question, scenario.question);
    outcomes.push({ route: data.task, previewCount: scenario.files.length, receiptQuestion: receipt.question, overlay: data.overlay.type });
  }
  assert.ok(requests.every(body => Object.keys(body).sort().join(',') === 'asset_ids,question'));
  assert.ok(previews.every(status => status === 200)); assert.equal(errors.length, 0);
  console.log(JSON.stringify({ outcomes, noFrontendModeSent: true, previewStatuses: previews, errors }, null, 2));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
