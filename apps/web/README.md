# SatQuery AI · Query Notebook

React and Python implement the user-approved Query Notebook. The frontend sends **only asset IDs and the question** to the API. Python selects single-image, change, optical–SAR, or rejection. The route indicators are read-only.

## Run the notebook and main API

From the repository root, after the Python setup in the root README:

```powershell
npm --prefix apps/web ci
npm --prefix apps/web run build
.\.venv\Scripts\python.exe apps\web\server.py
```

Open http://127.0.0.1:5173. One Python process serves the built frontend and API under `/api`; live Tool 2 inference additionally requires the [separate MCI worker](../../docs/TOOL2.md#start-the-model-worker). API docs are at `/api/docs`. Use `--port 5181` for an alternate port.

For frontend development, run these in separate terminals:

```powershell
.\.venv\Scripts\python.exe apps\web\server.py --port 8000
npm --prefix apps/web run dev
```

Vite forwards `/api` without rewriting the path. The backend-only Uvicorn command in the root README is separate; use `server.py` for the frontend's combined API and raster-preview endpoint.

## Workflow

- River corridor opens as a labelled illustrative example. The demo selector loads prepared scene/question combinations; it does not select a live analysis tool.
- New investigation starts empty. Add one or two GeoTIFFs, optionally supply modality and dates, then validate and attach them. Temporal routing requires dates, either from metadata or the upload form.
- Ask a question. Input validity, modality, dates, grid compatibility, and question wording determine the route on the server.
- Compare side by side or with a swipe. Optical/SAR/Blend controls change the display; Blend is labelled as a visual blend, not analytical fusion.
- Expand metadata, warnings, receipt stages, and parameters. Download JSON preserves the result; Export receipt includes the submitted question.
- Live Tool 1 results show Scene and Land-cover overlay modes, class badges (water, vegetation, built-up), and an overlay PNG. Analysis is rule-based NDWI/NDVI/brightness; confidence is not measured. A single SAR file still routes to the single-image task but is not classified with optical indices.
- Live Tool 2 results show Compare, Overlay, and Semantic mask modes, a model change description, changed pixels/percentages, road/building change, optional area, and evidence downloads. Inputs must be exact-grid 256×256 three-band uint8 RGB optical GeoTIFFs with different dates. A ready worker is required.
- Live Tool 3 results show Optical-only, SAR-only, and Fused candidate maps, statistics, and SAR contribution. See [Tool 3 inputs](../../docs/TOOL3_HANDOFF.md).
- Rejected inputs never receive an overlay. Tool 2 worker failures surface as errors, with no stub fallback.
- Tool 2 captions describe the image pair; they are not conditioned on the question. Confidence for Tools 1/2/3 is not measured. No-change results say “No detected change”; missing/expired evidence displays an unavailable state.

Investigations live in memory in the browser tab. Uploads expire after 24 hours by default. Refresh resets the notebook without extending upload retention.

## Libraries and assets

React, TypeScript, Vite, Lucide React, and self-hosted DM Sans. Libraries.dev's **border-beam** marks question focus/processing and **thinking-orbs** supplies waiting feedback. Both respect reduced motion; neither requires Pro.

`public/assets/river-pair.png` is generated illustrative scenery, not scientific data. Its exact prompt is embedded and provided alongside it. Real previews come from the actual uploaded raster via bounded Python thumbnails, percentile display stretch, and no-data transparency. Preview failure does not invalidate a queryable asset.

## Verification

```powershell
npm --prefix apps/web run build
.\.venv\Scripts\python.exe -m pytest
```

Browser checks use Playwright and installed Microsoft Edge. With the combined server running, generate the ordinary fixtures and synthetic Tool 3 Pack C (the Pack C generator requires a new output directory):

```powershell
.\.venv\Scripts\python.exe tests\web\create-fixtures.py
.\.venv\Scripts\python.exe -m satquery.tools.tool3.pack_c demo/packs/C/generated
$env:SATQUERY_TEST_URL = 'http://127.0.0.1:5173'
node tests\web\inspect-notebook.cjs
node tests\web\verify-tool2.cjs
node tests\web\verify-tool3.cjs
node tests\web\verify-live-flow.cjs
```

These scripts cover notebook presentation and the dedicated Tool 1/2/3 evidence views; Tool 2 API/artifact responses are mocked in `verify-tool2.cjs`. `verify-live-flow.cjs` hits the real API with the ordinary 64×96 fixtures: single-image is live (heatmap overlay, not a stub), and a dated optical pair is rejected as unsupported Tool 2 input (not 256×256), not as a change stub. Fixtures and outputs are Git-ignored. No deployment is included.

Use `node tests/web/verify-tool2.cjs` for Tool 2 frontend behavior (mocked API/artifacts), and `node tests/web/verify-tool3.cjs` for Tool 3. Real Tool 2 worker/browser verification is opt-in and needs the checkpoint, dataset fixtures, CUDA environment, and built frontend; see [Tool 2 verification](../../docs/TOOL2.md#verification).
