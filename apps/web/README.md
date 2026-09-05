# SatQuery AI · Query Notebook

React and Python implement the user-approved Query Notebook. The frontend sends **only asset IDs and the question** to the API. Python selects single-image, change, optical–SAR, or rejection. The route indicators are read-only.

## Run the complete app

From the repository root, after the Python setup in the root README:

```powershell
npm --prefix apps/web ci
npm --prefix apps/web run build
.\.venv\Scripts\python.exe apps\web\server.py
```

Open http://127.0.0.1:5173. One Python process serves the built frontend and API under `/api`; API docs are at `/api/docs`. Use `--port 5181` for an alternate port.

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
- Real specialist tools remain stubs. Real uploads return a truthful routing receipt with no computed findings or analysis overlay. Rejected inputs never receive an overlay.

Investigations live in memory in the browser tab. Uploads expire after 24 hours by default. Refresh resets the notebook without extending upload retention.

## Libraries and assets

React, TypeScript, Vite, Lucide React, and self-hosted DM Sans. Libraries.dev's **border-beam** marks question focus/processing and **thinking-orbs** supplies waiting feedback. Both respect reduced motion; neither requires Pro.

`public/assets/river-pair.png` is generated illustrative scenery, not scientific data. Its exact prompt is embedded and provided alongside it. Real previews come from the actual uploaded raster via bounded Python thumbnails, percentile display stretch, and no-data transparency. Preview failure does not invalidate a queryable asset.

## Verification

```powershell
npm --prefix apps/web run build
.\.venv\Scripts\python.exe -m pytest
```

Browser checks use Playwright and installed Microsoft Edge. With the combined server running:

```powershell
.\.venv\Scripts\python.exe tests\web\create-fixtures.py
$env:SATQUERY_TEST_URL = 'http://127.0.0.1:5173'
node tests\web\inspect-notebook.cjs
node tests\web\verify-live-flow.cjs
```

Checks cover demo workflows, keyboard comparison, rejection, downloads, desktop/mobile overflow, uploads/previews, all three server-selected routes, and grid rejection. Fixtures and outputs are Git-ignored. No deployment or analytical model implementation is included.
