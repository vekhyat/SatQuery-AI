// Run against the built local notebook with Pack C generated first.
const { chromium } = require('../../apps/web/node_modules/@playwright/test');
const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.SATQUERY_TEST_URL || 'http://127.0.0.1:5173', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'New investigation', exact: true }).click();
    await page.getByLabel('Choose GeoTIFF files').setInputFiles(['sar', 'optical'].map(name => path.join(__dirname, '../../demo/packs/C/generated', name + '.tif')));
    await page.getByRole('button', { name: 'Validate and attach', exact: true }).click();
    await page.getByRole('region', { name: 'Attach GeoTIFF scenes' }).waitFor({ state: 'hidden', timeout: 20000 });
    await page.getByLabel('Question about your satellite scenes').fill('Use the optical and SAR images together to identify built-up and water-covered regions.');
    const responseWait = page.waitForResponse(response => response.url().endsWith('/api/query'));
    await page.getByRole('button', { name: 'Ask SatQuery', exact: true }).click();
    const result = await (await responseWait).json();
    assert.equal(result.task, 'optical_sar');
    assert.equal(result.receipt.trace.at(-1).status, 'ok');
    const region = page.getByRole('region', { name: 'Computed optical and SAR candidate maps' });
    await region.waitFor();
    const sources = [];
    for (const name of ['Optical-only', 'SAR-only', 'Fused']) {
      await region.getByRole('button', { name, exact: true }).click();
      const image = region.getByRole('img');
      await page.waitForFunction(() => {
        const img = document.querySelector('.tool3-map-image img');
        return img && img.complete && img.naturalWidth > 0;
      });
      sources.push(await image.getAttribute('src'));
      const layer = name === 'Optical-only' ? 'optical_only' : name === 'SAR-only' ? 'sar_only' : 'fused';
      assert.equal(sources.at(-1), result.facts.layer_urls[layer]);
      assert.match(await region.innerText(), new RegExp(result.facts.layers[layer].water.pixels.toLocaleString()));
    }
    assert.equal(new Set(sources).size, 3);
    assert.equal(await page.getByText('Confidence: not measured', { exact: false }).count() > 0, true);
    assert.equal(await page.getByText('Confidence: 0%', { exact: false }).count(), 0);
    assert.deepEqual(errors, []);
    const output = process.env.SATQUERY_SCREENSHOT || path.join(__dirname, 'tool3-live.png');
    await page.screenshot({ path: output, fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), true);
    const mobileOutput = output.replace(/\.png$/, '-mobile.png');
    await page.screenshot({ path: mobileOutput, fullPage: true });
    fs.writeFileSync(output.replace(/\.png$/, '.json'), JSON.stringify({ passed: true, layer_urls: sources, sar_contribution: result.facts.sar_contribution, javascript_errors: errors }, null, 2));
    console.log('Tool 3 browser check passed: upload, route, three toggles, counts, confidence and mobile layout.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
