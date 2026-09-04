# SIH26167 · SatQuery AI

ISRO problem statement: **SatQuery AI** — an interactive vision-language assistant for multimodal remote-sensing image analysis through text queries.

**Repo:** https://github.com/vekhyat/SIH26167

## Start here

Open [`handbook.html`](handbook.html) in a browser. That is the team briefing: architecture, teaching notes (including LoRA), work order, checklists, PPT/video plan.

## Docs in this repo

`handbook.html` is the complete team handbook, including the architecture,
six-person work split, technical plan, checklists, and presentation guidance.

## What we are building

A website: upload satellite file(s), ask a question, a **code router** picks one of three tools (single image, before/after change, optical+SAR), and facts are drawn on a map with a visible receipt.

Not three LLMs. A VLM/LoRA upgrade, if any, sits inside the single-image tool after the 12 Sep internal demo.

## Backend vertical slice

The first executable backend contains three deliberately separate parts:

1. The **checker** opens a GeoTIFF and verifies its geospatial metadata. For a pair, it requires the same CRS, dimensions, and pixel grid.
2. The **router** applies visible if/then rules to choose `single_image`, `change`, `optical_sar`, or `reject`.
3. The **API** is the front door used by Postman and, later, the website. It stores each upload for 24 hours and returns stable JSON.

The specialist analysis tools are currently honest stubs. A successful route proves that the desk works; it does not claim that image analysis has happened.

### Set up on Windows

Python 3.12 or newer is required.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Start the local-only API:

```powershell
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API page. The three public endpoints are:

- `GET /health`
- `POST /upload`
- `POST /query`

### Upload and query

Upload each GeoTIFF separately. Optional `modality` and `acquisition_date` fields supply metadata that is missing from the file.

```powershell
curl.exe -X POST http://127.0.0.1:8000/upload `
  -F "file=@C:\path\to\scene.tif" `
  -F "modality=optical" `
  -F "acquisition_date=2024-02-04"
```

Copy the returned `asset_id`, then query one asset or a compatible pair:

```powershell
curl.exe -X POST http://127.0.0.1:8000/query `
  -H "Content-Type: application/json" `
  -d '{"asset_ids":["PASTE-ASSET-UUID"],"question":"Describe the land cover"}'
```

For change analysis, upload two aligned optical GeoTIFFs with different dates and place both IDs in `asset_ids`. For optical–SAR analysis, upload an exact-grid optical/SAR pair.

### Verify

```powershell
python -m pytest
python -m compileall apps satquery tests
```

Configuration is optional: `SATQUERY_RUNTIME_DIR`, `SATQUERY_MAX_UPLOAD_MIB`, `SATQUERY_RETENTION_HOURS`, and comma-separated `SATQUERY_CORS_ORIGINS`. The API binds to localhost through the Uvicorn command above; authentication and deployment are intentionally deferred.
