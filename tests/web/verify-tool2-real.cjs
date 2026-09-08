// Opt-in browser check against the real main API and real MCI worker stack.
const { chromium } = require('../../apps/web/node_modules/@playwright/test');
const assert = require('node:assert/strict');

for (const name of ['TOOL2_E2E_POSITIVE_BEFORE', 'TOOL2_E2E_POSITIVE_AFTER', 'TOOL2_E2E_NO_CHANGE_BEFORE', 'TOOL2_E2E_NO_CHANGE_AFTER']) {
  if (!process.env[name]) throw new Error(`${name} is required`);
}

(async () => {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
    const requests = [];
    const artifactResponses = [];
    const errors = [];
    page.on('request', request => requests.push(request.url()));
    page.on('response', response => {
      if (response.url().includes('/api/artifacts/tool2/')) artifactResponses.push({ url: response.url(), status: response.status() });
    });
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.SATQUERY_TEST_URL, { waitUntil: 'networkidle' });

    async function run(before, after, dates) {
      await page.getByRole('button', { name: 'New investigation', exact: true }).click();
      await page.getByLabel('Choose GeoTIFF files').setInputFiles([before, after]);
      const dateInputs = page.getByLabel('Acquisition date', { exact: true });
      await dateInputs.nth(0).fill(dates[0]);
      await dateInputs.nth(1).fill(dates[1]);
      await page.getByRole('button', { name: 'Validate and attach', exact: true }).click();
      await page.getByRole('region', { name: 'Attach GeoTIFF scenes' }).waitFor({ state: 'hidden', timeout: 30000 });
      await page.getByLabel('Question about your satellite scenes').fill('What changed?');
      const query = page.waitForResponse(response => response.url().endsWith('/api/query'), { timeout: 40000 });
      await page.getByRole('button', { name: 'Ask SatQuery', exact: true }).click();
      const response = await query;
      assert.equal(response.status(), 200);
      return response.json();
    }

    const positive = await run(process.env.TOOL2_E2E_POSITIVE_BEFORE, process.env.TOOL2_E2E_POSITIVE_AFTER, ['2024-01-01', '2024-02-01']);
    assert.equal(positive.task, 'change');
    assert.deepEqual(positive.tools, ['checker_v1', 'router_v1', 'change_mci_v1']);
    const view = page.getByRole('region', { name: 'Change analysis evidence' });
    await view.waitFor();
    assert.equal(await view.getByRole('button', { name: 'Compare', exact: true }).getAttribute('aria-pressed'), 'true');
    assert.equal(await view.locator('.scene-viewer__pair').count(), 1);
    assert.match(await view.innerText(), /test_000004_before\.tif/i);
    assert.match(await view.innerText(), /test_000004_after\.tif/i);
    assert.match(await view.innerText(), /19,938/);
    assert.match(await view.innerText(), /30\.42%/);
    assert.match(await view.innerText(), /vegetation has been removed/);
    assert.equal(await page.getByText('Confidence: not measured', { exact: false }).count() > 0, true);
    assert.equal(await page.getByText('Confidence: 0%', { exact: false }).count(), 0);
    await view.getByRole('button', { name: 'Overlay', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.tool2-change-view__image img')?.naturalWidth === 256);
    await view.getByRole('button', { name: 'Semantic mask', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.tool2-change-view__image img')?.naturalWidth === 256);
    assert.match(await view.innerText(), /Unchanged\/background/);
    assert.match(await view.innerText(), /Road change/);
    assert.match(await view.innerText(), /Building change/);
    for (const name of ['Overlay PNG', 'Semantic mask PNG', 'Binary mask PNG', 'Components JSON']) {
      assert.match(await view.getByRole('link', { name, exact: true }).getAttribute('href'), /^\/api\/artifacts\/tool2\//);
    }

    const noChange = await run(process.env.TOOL2_E2E_NO_CHANGE_BEFORE, process.env.TOOL2_E2E_NO_CHANGE_AFTER, ['2024-03-01', '2024-04-01']);
    assert.equal(noChange.facts.changed_pixels, 0);
    const noChangeView = page.getByRole('region', { name: 'Change analysis evidence' });
    await noChangeView.waitFor();
    assert.match(await noChangeView.innerText(), /No detected change/);
    assert.match(await noChangeView.innerText(), /0\.00%/);
    assert.equal(await noChangeView.getByText('Road change', { exact: false }).count(), 0);
    assert.equal(await noChangeView.getByText('Building change', { exact: false }).count(), 0);
    assert.match(await page.getByRole('region', { name: 'Analysis answer' }).innerText(), /scene is the same as before/i);

    assert.equal(requests.some(url => url.includes('127.0.0.1:8012')), false);
    assert.equal(requests.some(url => url.includes('MCI_model.pth')), false);
    assert.equal(artifactResponses.length >= 2, true);
    assert.equal(artifactResponses.every(item => item.status === 200), true);
    assert.deepEqual(errors, []);
    console.log('TOOL2_REAL_BROWSER_REPORT=' + JSON.stringify({
      positive_caption: positive.facts.caption.text,
      positive_changed_pixels: positive.facts.changed_pixels,
      no_change_caption: noChange.facts.caption.text,
      no_change_changed_pixels: noChange.facts.changed_pixels,
      artifact_responses: artifactResponses,
      direct_worker_requests: requests.filter(url => url.includes('127.0.0.1:8012')),
      page_errors: errors,
    }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
