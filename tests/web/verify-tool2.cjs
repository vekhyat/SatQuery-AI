// Browser verification for the built notebook. It intercepts only the API/artifact
// boundary, leaving the React application and its user interactions real.
const { chromium } = require('../../apps/web/node_modules/@playwright/test');
const assert = require('node:assert/strict');

const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL0vwAAAABJRU5ErkJggg==',
  'base64',
);

const RESULT = {
  task: 'change',
  tools: ['change_mci_v1'],
  parameters: { before_asset_id: 'asset-before', after_asset_id: 'asset-after' },
  facts: {
    caption: { text: 'the vegetation has been removed and a road with villas built along appears', question_conditioned: false },
    changed_pixels: 19938,
    changed_percent: 30.4229736328125,
    classes: {
      road_change: { percent_of_valid_pixels: 11.263671875 },
      building_change: { percent_of_valid_pixels: 19.1593017578125 },
    },
    physical_area_m2: 12500,
    physical_area_hectares: 1.25,
    confidence_status: 'not_measured',
    artifacts: {
      overlay: '/artifacts/tool2/0123456789abcdef0123456789abcdef/overlay.png',
      semantic_mask_rgb: '/artifacts/tool2/0123456789abcdef0123456789abcdef/semantic_mask_rgb.png',
      binary_mask: '/artifacts/tool2/0123456789abcdef0123456789abcdef/change_binary_mask.png',
      components: '/artifacts/tool2/0123456789abcdef0123456789abcdef/components.json',
      unsafe: 'file:///C:/Users/Aryaveer/private.png',
    },
  },
  answer_text: 'The vegetation has been removed. Changed pixels: 19,938 (30.42% of valid pixels).',
  confidence: 0,
  warnings: ['Model confidence is not calibrated.'],
  overlay: { type: 'change_mask', file: '/artifacts/tool2/0123456789abcdef0123456789abcdef/overlay.png' },
  receipt: {
    why_this_tool: 'Dated optical images are a change pair.',
    rejected: false,
    reason: null,
    trace: [
      { stage: 'checker', status: 'ok', message: 'Validated.', details: {} },
      { stage: 'router', status: 'ok', message: 'Change route.', details: {} },
      { stage: 'tool', status: 'ok', message: 'Analysis complete.', details: {} },
    ],
  },
};

const NO_CHANGE = {
  ...RESULT,
  facts: {
    ...RESULT.facts,
    caption: { text: 'the scene is the same as before', question_conditioned: false },
    changed_pixels: 0,
    changed_percent: 0,
    classes: {
      road_change: { percent_of_valid_pixels: 0 },
      building_change: { percent_of_valid_pixels: 0 },
    },
    physical_area_m2: null,
    physical_area_hectares: null,
    artifacts: {
      overlay: '/artifacts/tool2/fedcba9876543210fedcba9876543210/overlay.png',
      semantic_mask_rgb: '/artifacts/tool2/fedcba9876543210fedcba9876543210/semantic_mask_rgb.png',
      binary_mask: '/artifacts/tool2/fedcba9876543210fedcba9876543210/change_binary_mask.png',
      components: '/artifacts/tool2/%2e%2e/access.json',
    },
  },
  answer_text: 'The scene is the same as before. Changed pixels: 0 (0.00% of valid pixels).',
};

const TOOL3 = {
  task: 'optical_sar', tools: ['optical_sar_v1'], parameters: {},
  facts: { layer_urls: { optical_only: '/artifacts/tool3/run/optical.png', sar_only: '/artifacts/tool3/run/sar.png', fused: '/artifacts/tool3/run/fused.png' }, layers: { fused: { water: { pixels: 12 }, builtup: { pixels: 8 } } } },
  answer_text: 'Optical and SAR candidate maps are available.', confidence: 0, warnings: [], overlay: { type: 'none', file: null },
  receipt: { why_this_tool: 'Optical and SAR pair.', rejected: false, reason: null, trace: [{ stage: 'checker', status: 'ok', message: 'Validated.', details: {} }, { stage: 'router', status: 'ok', message: 'Fusion route.', details: {} }, { stage: 'tool', status: 'ok', message: 'Done.', details: {} }] },
};

const TOOL1 = {
  task: 'single_image', tools: ['single_image_stub_v0'], parameters: {}, facts: {}, answer_text: 'Analysis is not connected.', confidence: 0, warnings: [], overlay: { type: 'none', file: null },
  receipt: { why_this_tool: 'One scene.', rejected: false, reason: null, trace: [{ stage: 'checker', status: 'ok', message: 'Validated.', details: {} }, { stage: 'router', status: 'ok', message: 'Single route.', details: {} }, { stage: 'tool', status: 'stub', message: 'Stub.', details: {} }] },
};

const REJECTED = {
  task: 'reject', tools: [], parameters: {}, facts: {}, answer_text: 'These inputs cannot be analysed.', confidence: 0, warnings: [], overlay: { type: 'none', file: null },
  receipt: { why_this_tool: 'Inputs incompatible.', rejected: true, reason: 'These inputs cannot be analysed.', trace: [{ stage: 'checker', status: 'rejected', message: 'Rejected.', details: {} }] },
};

function upload(assetId, date) {
  return {
    asset_id: assetId,
    original_name: `${assetId}.tif`, size_bytes: 100, sha256: 'a'.repeat(64),
    created_at: '2026-09-09T00:00:00Z', expires_at: '2026-09-10T00:00:00Z', warnings: [],
    metadata: {
      driver: 'GTiff', width: 256, height: 256, band_count: 3, dtypes: ['uint8'], crs: 'EPSG:32643',
      bounds: { left: 0, bottom: 0, right: 256, top: 256 }, transform: [1, 0, 0, 0, -1, 256], resolution: [1, 1], nodata: null,
      band_descriptions: [null, null, null], tags: {}, modality: 'optical', acquisition_date: date,
      provenance: { modality: { source: 'user', detected_value: 'optical', detected_source: 'user' }, acquisition_date: { source: 'user', detected_value: date, detected_source: 'user' } },
    },
  };
}

(async () => {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
    const errors = [];
    let uploadCount = 0;
    let queryCount = 0;
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/health') return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
      if (path === '/api/upload') return route.fulfill({ contentType: 'application/json', body: JSON.stringify(upload(uploadCount++ === 0 ? 'asset-before' : 'asset-after', uploadCount === 1 ? '2026-01-01' : '2026-02-01')) });
      if (path.startsWith('/api/preview/')) return route.fulfill({ contentType: 'image/png', body: PNG });
      if (path === '/api/query') return route.fulfill({ contentType: 'application/json', body: JSON.stringify([RESULT, NO_CHANGE, TOOL3, TOOL1, REJECTED][queryCount++] ?? REJECTED) });
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
    });
    await page.route('**/artifacts/tool2/**', route => {
      const filename = route.request().url().split('/').at(-1);
      if (route.request().url().includes('fedcba9876543210') && filename === 'overlay.png') return route.fulfill({ status: 404, contentType: 'text/plain', body: 'expired' });
      return route.fulfill({ status: 200, contentType: filename === 'components.json' ? 'application/json' : 'image/png', body: filename === 'components.json' ? '{"components":[]}' : PNG });
    });
    await page.route('**/artifacts/tool3/**', route => route.fulfill({ status: 200, contentType: 'image/png', body: PNG }));
    await page.goto(process.env.SATQUERY_TEST_URL || 'http://127.0.0.1:5173', { waitUntil: 'networkidle' });

    async function runChange(question) {
      await page.getByRole('button', { name: 'New investigation', exact: true }).click();
      await page.getByLabel('Choose GeoTIFF files').setInputFiles([
        { name: 'before.tif', mimeType: 'image/tiff', buffer: Buffer.from('before') },
        { name: 'after.tif', mimeType: 'image/tiff', buffer: Buffer.from('after') },
      ]);
      await page.getByRole('button', { name: 'Validate and attach', exact: true }).click();
      await page.getByRole('region', { name: 'Attach GeoTIFF scenes' }).waitFor({ state: 'hidden' });
      await page.getByLabel('Question about your satellite scenes').fill(question);
      await page.getByRole('button', { name: 'Ask SatQuery', exact: true }).click();
    }

    await runChange('What changed?');
    const view = page.getByRole('region', { name: 'Change analysis evidence' });
    await view.waitFor({ timeout: 5_000 });
    await expectText(view, 'Model change description');
    await expectText(view, '30.42%');
    await expectText(view, '19,938');
    await expectText(view, 'Road change');
    await expectText(view, 'Building change');
    await expectText(view, '12,500 m²');
    assert.equal(await page.getByText('Confidence: 0%', { exact: false }).count(), 0);
    assert.equal(await page.getByText('Confidence: not measured', { exact: false }).count() > 0, true);

    for (const [button, expected] of [['Overlay', 'overlay.png'], ['Semantic mask', 'semantic_mask_rgb.png']]) {
      await view.getByRole('button', { name: button, exact: true }).click();
      const image = view.getByRole('img');
      await image.waitFor();
      assert.match(await image.getAttribute('src'), new RegExp(expected.replace('.', '\\.')));
    }
    for (const name of ['Overlay PNG', 'Semantic mask PNG', 'Binary mask PNG', 'Components JSON']) {
      const href = await view.getByRole('link', { name, exact: true }).getAttribute('href');
      assert.match(href || '', /^\/artifacts\/tool2\//);
    }
    assert.equal(await view.getByRole('link', { name: /unsafe/i }).count(), 0);

    await runChange('What changed on the second pair?');
    const noChange = page.getByRole('region', { name: 'Change analysis evidence' }).last();
    await noChange.waitFor({ timeout: 5_000 });
    await expectText(noChange, 'No detected change');
    await expectText(noChange, '0.00%');
    assert.equal(await noChange.getByText('Road change', { exact: false }).count(), 0);
    assert.equal(await noChange.getByText('Building change', { exact: false }).count(), 0);
    assert.equal(await noChange.getByText('m²', { exact: false }).count(), 0);
    assert.equal(await noChange.getByRole('link', { name: 'Components JSON', exact: true }).count(), 0);
    await noChange.getByRole('button', { name: 'Overlay', exact: true }).click();
    await expectText(noChange, 'This evidence item is no longer available.');
    await noChange.getByRole('button', { name: 'Semantic mask', exact: true }).click();
    await noChange.getByRole('img').waitFor();

    await runChange('Compare optical and SAR.');
    await page.getByRole('region', { name: 'Computed optical and SAR candidate maps' }).waitFor();
    assert.equal(await page.getByRole('region', { name: 'Change analysis evidence' }).count(), 0);

    await page.getByRole('button', { name: 'New investigation', exact: true }).click();
    await page.getByLabel('Choose GeoTIFF files').setInputFiles([{ name: 'single.tif', mimeType: 'image/tiff', buffer: Buffer.from('single') }]);
    await page.getByRole('button', { name: 'Validate and attach', exact: true }).click();
    await page.getByRole('region', { name: 'Attach GeoTIFF scenes' }).waitFor({ state: 'hidden' });
    await page.getByLabel('Question about your satellite scenes').fill('Describe this scene.');
    await page.getByRole('button', { name: 'Ask SatQuery', exact: true }).click();
    assert.equal(await page.getByRole('region', { name: 'Change analysis evidence' }).count(), 0);
    assert.equal(await page.getByRole('region', { name: 'Computed optical and SAR candidate maps' }).count(), 0);

    await runChange('Reject this pair.');
    await page.getByText('These inputs cannot be analysed', { exact: true }).waitFor();
    assert.equal(await page.getByRole('region', { name: 'Change analysis evidence' }).count(), 0);
    assert.deepEqual(errors, []);
    console.log('Tool 2 browser check passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

async function expectText(locator, value) {
  assert.equal(await locator.getByText(value, { exact: false }).count() > 0, true, `Expected ${value}`);
}
