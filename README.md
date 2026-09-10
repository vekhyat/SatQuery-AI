# SIH26167 · SatQuery AI

ISRO problem statement: **SatQuery AI** — an interactive vision-language assistant for multimodal remote-sensing image analysis through text queries.

**Repo:** https://github.com/vekhyat/SIH26167

## Start here

Open [`docs/handbook.html`](docs/handbook.html) in a browser. That is the team briefing: architecture, teaching notes (including LoRA), work order, checklists, PPT/video plan.

## Layout

```text
docs/           Handbook, product brief, and design system
satquery/       Checker, router, contracts, storage, specialist adapters and Tool 3
apps/api/       FastAPI health, upload, and query
apps/web/       Query Notebook (React) and combined local server
experiments/    Isolated Tool 2 MCI model worker and standalone analysis
requirements/   Separate Python 3.11 worker dependency pins
tests/          Backend, opt-in model/E2E, and notebook browser checks
```

## Docs in this repo

`docs/handbook.html` is the complete team handbook, including the architecture,
six-person work split, technical plan, checklists, and presentation guidance.
For current implemented behavior, start with this README and the [Tool 2 guide](docs/TOOL2.md) or [Tool 3 handoff](docs/TOOL3_HANDOFF.md). The handbook includes earlier plans; current source code and contracts take precedence.
The notebook’s visual rules are in [`docs/DESIGN.md`](docs/DESIGN.md).

## What we are building

A website: upload satellite file(s), ask a question, a **code router** picks one of three tools (single image, before/after change, optical+SAR), and results appear as raster evidence with a visible receipt.

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
optical–SAR analysis. Tool 1 is connected as `single_image_v1`: rule-based land-cover
from NDWI, NDVI, and brightness, with a heatmap overlay PNG at
`/artifacts/tool1/{run_id}/overlay.png`. Facts include labels, water, vegetation,
built-up, `is_pack_a`, and `confidence_status` (`not_measured`); `confidence=0.0`
means not measured, the same as Tools 2 and 3. Tool 2 is connected as `change_mci_v1`: a separate Python 3.11 worker runs the pretrained Change-Agent MCI checkpoint and returns a change caption, semantic masks, and statistics. Tool 3 runs as `optical_sar_v1` and computes water/built-up candidate maps. `single_image_stub_v0` may remain in the registry; the live single-image route is `single_image_v1`.

The main API requires Python 3.12+ and does not import Torch. The MCI worker has its own pinned dependencies and must be started separately; installing the main package does not install the worker or checkpoint. Training, LoRA, question-conditioned VQA, and deployment are not implemented.

The Query Notebook lives in `apps/web`. Dependency manifests are `pyproject.toml`
and `apps/web/package.json`.

## Backend vertical slice

The first executable backend contains three deliberately separate parts:

1. The **checker** opens a GeoTIFF and verifies its geospatial metadata. For a pair, it requires the same CRS, dimensions, and pixel grid.
2. The **router** applies visible if/then rules to choose `single_image`, `change`, `optical_sar`, or `reject`.
3. The **API** is the front door used by the Query Notebook and API clients. It stores each upload for 24 hours and returns stable JSON.

Tools 1, 2, and 3 run through `/upload` and `/query`. Tool 1 adds Scene and Land-cover overlay views with class badges. Tool 2 adds Compare, Overlay, and Semantic mask views; Tool 3 shows three computed candidate maps. A single SAR file still routes to the single-image task (not optical_sar) but is not classified with optical indices. See the [Tool 2 setup and limits](docs/TOOL2.md) before querying a temporal pair. See [Tool 3 handoff](docs/TOOL3_HANDOFF.md) for band requirements, Pack C, and integration details.

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

Open `http://127.0.0.1:8000/docs` for the interactive API page. The core endpoints are:

- `GET /health`
- `POST /upload`
- `POST /query`
- `GET /artifacts/tool1/{run_id}/{filename}` for completed single-image overlay evidence
- `GET /artifacts/tool2/{run_id}/{filename}` for completed change evidence
- `GET /artifacts/tool3/{run_id}/{filename}` for optical/SAR evidence

To run the Query Notebook with the API and raster previews in one process, see
[`apps/web/README.md`](apps/web/README.md):

```powershell
npm --prefix apps/web ci
npm --prefix apps/web run build
.\.venv\Scripts\python.exe apps\web\server.py
```

Then open `http://127.0.0.1:5173`. That server exposes the API under `/api`.
The Uvicorn command above is backend-only. Live Tool 2 analysis also needs the [separate MCI worker](docs/TOOL2.md#start-the-model-worker); the combined server does not launch it.

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

For change analysis, upload two exact-grid, 256×256, three-band uint8 RGB optical GeoTIFFs with different dates and place both IDs in `asset_ids`. The router orders them by date. The MCI worker must be ready; unavailable workers return an error without falling back to a stub. For optical–SAR analysis, upload an exact-grid optical/SAR pair with green/NIR/SWIR band descriptions and calibrated VV units; see `docs/TOOL3_HANDOFF.md`.

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

This is a schema-valid live Tool 1 example. Labels, overlay path, warnings, and
trace details vary with the uploaded file. `confidence` is uncalibrated: `0.0`
means not measured, not a validated accuracy score.

```json
{
  "task": "single_image",
  "tools": ["checker_v1", "router_v1", "single_image_v1"],
  "parameters": {
    "asset_id": "11111111-1111-4111-8111-111111111111"
  },
  "facts": {
    "summary": "This scene contains: vegetation.",
    "labels": ["vegetation"],
    "water": false,
    "vegetation": true,
    "built_up": false,
    "is_pack_a": false,
    "confidence_status": "not_measured"
  },
  "answer_text": "This scene contains: vegetation.",
  "confidence": 0.0,
  "warnings": [
    "3-band RGB image detected without NIR band. Rule-based visible detection used."
  ],
  "overlay": {
    "type": "heatmap",
    "file": "/artifacts/tool1/0123456789abcdef0123456789abcdef/overlay.png"
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
          "tool": "single_image_v1"
        }
      },
      {
        "stage": "tool",
        "status": "ok",
        "message": "single_image_v1 completed specialist analysis.",
        "details": {
          "tool": "single_image_v1",
          "facts_returned": true,
          "overlay_type": "heatmap"
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
| `facts` | Specialist output dictionary. Tool 1 includes `summary`, `labels`, `water`, `vegetation`, `built_up`, `is_pack_a`, and `confidence_status` (`not_measured`). Tool 2 includes caption provenance, changed-pixel and class statistics, optional physical area, components, model/timing information, and artifact URLs. Tool 3 includes class statistics, `sar_contribution`, `layer_urls`, artifact links and an uncalibrated confidence status. Unused registry stubs return an empty dictionary. |
| `answer_text` | Composer-owned text for the UI. |
| `confidence` | Number from 0 to 1. Live Tools 1/2/3 use 0.0 to mean not measured, not a validated accuracy metric. Unused registry stubs also use 0. |
| `warnings` | List of messages about metadata, limitations, and tool execution. |
| `overlay` | `type` is `heatmap`, `change_mask`, or `none`; `file` is a string or `null`. Live Tool 1 returns `heatmap` and a `/artifacts/tool1/{run_id}/overlay.png` file. Unused registry stubs and rejections return `none` and `null`. |
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

The composer builds Tool 1 text from `facts.summary`, Tool 2 text from the model caption and measured mask statistics, and Tool 3 text from `facts.sar_contribution`. Absent facts retain the stub explanation. The service records `ok` for completed specialist runs and `rejected` for unsupported datasets. `single_image_stub_v0` may remain in the registry, but the live single-image route is `single_image_v1`. Tool 2 captions are not conditioned on the submitted question, and `confidence=0.0` means not measured.

Tool 2 worker failures use `ErrorEnvelope`: busy is HTTP 429, unavailable/not-ready is 503, timeout is 504, and invalid worker responses or inference failures are 502. Unsupported Tool 2 input becomes an HTTP 200 rejection envelope with no overlay.

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

The ordinary suite is checkpoint-free. Torch is imported only for real inference; helper and worker-contract tests run without it. Tensor preprocessing skips when Torch is absent. Real CUDA/checkpoint checks are opt-in; see [Tool 2 verification](docs/TOOL2.md#verification).

Configuration is optional: `SATQUERY_RUNTIME_DIR`, `SATQUERY_MAX_UPLOAD_MIB`, `SATQUERY_RETENTION_HOURS`, and comma-separated `SATQUERY_CORS_ORIGINS`. Tool 2 adds `SATQUERY_MCI_WORKER_URL` (default `http://127.0.0.1:8012`), `SATQUERY_MCI_CONNECT_TIMEOUT_SECONDS` (1), and `SATQUERY_MCI_ANALYSIS_TIMEOUT_SECONDS` (15). The API binds to localhost through the Uvicorn command above; authentication and deployment are intentionally deferred.
