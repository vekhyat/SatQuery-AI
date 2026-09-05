# SIH26167 · SatQuery AI

ISRO problem statement: **SatQuery AI** — an interactive vision-language assistant for multimodal remote-sensing image analysis through text queries.

**Repo:** https://github.com/vekhyat/SIH26167

## Start here

Open [`docs/handbook.html`](docs/handbook.html) in a browser. That is the team briefing: architecture, teaching notes (including LoRA), work order, checklists, PPT/video plan.

## Layout

```text
docs/           Handbook, product brief, and design system
satquery/       Checker, router, contracts, storage
apps/api/       FastAPI health, upload, and query
apps/web/       Query Notebook (React) and combined local server
tests/          API tests and tests/web for the notebook
```

## Docs in this repo

`docs/handbook.html` is the complete team handbook, including the architecture,
six-person work split, technical plan, checklists, and presentation guidance.
The notebook’s visual rules are in [`docs/DESIGN.md`](docs/DESIGN.md).

## What we are building

A website: upload satellite file(s), ask a question, a **code router** picks one of three tools (single image, before/after change, optical+SAR), and facts are drawn on a map with a visible receipt.

Not three LLMs. A VLM/LoRA upgrade, if any, sits inside the single-image tool after the 12 Sep internal demo.

## Chosen stack

| Layer | Choice | Role and current status |
|---|---|---|
| Frontend | React 19, TypeScript, Vite | Query Notebook in `apps/web`: upload, question, comparison, and receipt. |
| Frontend supporting libraries | Lucide React, DM Sans, Border Beam, Thinking Orbs | Icons, self-hosted type, question focus, and waiting feedback. Raster previews come from Python. |
| API | Python 3.12+, FastAPI, Uvicorn | Implemented health, GeoTIFF upload, and query endpoints. |
| Shared JSON contract | Pydantic 2 | Validates requests, upload metadata, tool results, and API responses in `satquery/contracts.py`. |
| Geospatial processing | Rasterio, NumPy, Affine | Reads raster metadata and checks CRS, dimensions, resolution, and exact pixel-grid alignment. |
| Routing and answers | Python rules, versioned tool registry, sentence composer | Chooses a specialist workflow and assembles its response. |
| Storage | Local filesystem with JSON asset records | Uploads expire after 24 hours by default; no database is required for this slice. |
| Backend checks | pytest, HTTPX TestClient, Python compileall | API, validation, storage, and upload-failure checks. |

The three specialist workflows are single-image analysis, temporal change, and
optical–SAR analysis. Their registered implementations currently return declared
stubs. A trained model, VLM, LoRA pipeline, and deployment provider have not been
implemented in this backend slice.

The Query Notebook lives in `apps/web`. Dependency manifests are `pyproject.toml`
and `apps/web/package.json`.

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

To run the Query Notebook with the API and raster previews in one process, see
[`apps/web/README.md`](apps/web/README.md):

```powershell
npm --prefix apps/web ci
npm --prefix apps/web run build
.\.venv\Scripts\python.exe apps\web\server.py
```

Then open `http://127.0.0.1:5173`. That server exposes the API under `/api`.
The Uvicorn command above is backend-only.

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

## Shared JSON templates

The authoritative models are in [`satquery/contracts.py`](satquery/contracts.py).
Use this implemented contract for integration where the earlier handbook sketch
differs: the response includes `receipt.trace` and does **not** define a top-level
`layers` field.

### Query request — frontend to API

Send this JSON to `POST /query`. Replace the example UUID with an `asset_id`
returned by `POST /upload`. Uploads use `multipart/form-data`, not this JSON body.

```json
{
  "asset_ids": ["11111111-1111-4111-8111-111111111111"],
  "question": "Describe the land cover"
}
```

`asset_ids` accepts one or two UUIDs. `question` must contain non-whitespace text
and be at most 500 characters. The backend chooses `task` from the assets and
question; the frontend does not send a tool name.

### Query response — API to frontend

This is a schema-valid single-image stub example, not a computed analysis result.
Warnings and trace messages may vary with the uploaded file.

```json
{
  "task": "single_image",
  "tools": ["checker_v1", "router_v1", "single_image_stub_v0"],
  "parameters": {
    "asset_id": "11111111-1111-4111-8111-111111111111"
  },
  "facts": {},
  "answer_text": "The request was validated and routed to single_image, but the specialist analysis tool is not connected yet.",
  "confidence": 0.0,
  "warnings": [
    "single_image_stub_v0 is a routing stub; no image analysis has been performed."
  ],
  "overlay": {
    "type": "none",
    "file": null
  },
  "receipt": {
    "why_this_tool": "One valid GeoTIFF matches the single-image workflow.",
    "rejected": false,
    "reason": null,
    "trace": [
      {
        "stage": "checker",
        "status": "ok",
        "message": "The input passed the geospatial checks.",
        "details": {}
      },
      {
        "stage": "router",
        "status": "ok",
        "message": "One valid GeoTIFF matches the single-image workflow.",
        "details": {
          "task": "single_image",
          "tool": "single_image_stub_v0"
        }
      },
      {
        "stage": "tool",
        "status": "stub",
        "message": "single_image_stub_v0 returned a declared stub result.",
        "details": {
          "facts_returned": false
        }
      }
    ]
  }
}
```

| Field | Contract |
|---|---|
| `task` | `single_image`, `change`, `optical_sar`, or `reject`. |
| `tools` | Versioned checker, router, and selected specialist identifiers; rejected routes have no specialist. |
| `parameters` | Single-image asset ID; before/after asset IDs and dates; optical/SAR asset IDs; or a rejection code. |
| `facts` | Specialist output dictionary. Currently empty for all stubs; agree on task-specific keys when implementing each tool. |
| `answer_text` | Composer-owned text for the UI. |
| `confidence` | Number from 0 to 1. Stub results use 0; this is not a validated accuracy metric. |
| `warnings` | List of messages about metadata, limitations, and tool execution. |
| `overlay` | `type` is `heatmap`, `change_mask`, or `none`; `file` is a string or `null`. Stubs return `none` and `null`. |
| `receipt` | Routing explanation, rejection flag/reason, and ordered checker/router/tool trace. |

### Specialist return — tool to service

Tool implementers return a `ToolResult` with these four fields. The service adds
the task, tool identifiers, parameters, answer text, and receipt to produce the
full `ResultEnvelope` above. The frontend reads that envelope.

```json
{
  "facts": {},
  "confidence": 0.0,
  "warnings": ["Analysis is not implemented yet."],
  "overlay": {
    "type": "none",
    "file": null
  }
}
```

The current composer uses a nonblank `facts.summary` when supplied, otherwise it
returns the stub explanation. Implementing a real tool also requires updating the
service's currently hardcoded `stub` trace status and its tests.

### API error

Malformed requests and upload/storage failures use `ErrorEnvelope`, for example:

```json
{
  "error": {
    "code": "request_validation_error",
    "message": "The request did not match the API contract.",
    "details": {
      "errors": []
    }
  }
}
```

Actual validation errors populate `details.errors` with location, message, and
type entries. A valid request that the router cannot support instead returns HTTP
200 with `task: "reject"`, `receipt.rejected: true`, and a non-null
`receipt.reason` in the normal result envelope.

### Verify

```powershell
python -m pytest
python -m compileall apps satquery tests
```

Configuration is optional: `SATQUERY_RUNTIME_DIR`, `SATQUERY_MAX_UPLOAD_MIB`, `SATQUERY_RETENTION_HOURS`, and comma-separated `SATQUERY_CORS_ORIGINS`. The API binds to localhost through the Uvicorn command above; authentication and deployment are intentionally deferred.
