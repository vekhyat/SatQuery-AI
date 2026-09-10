# Tool 2: temporal change analysis

Current implementation: `change_mci_v1`, integrated through revision `58d5b51`.
For the chronological implementation and original CUDA verification evidence,
see [the implementation handoff](TOOL2_IMPLEMENTATION_HANDOFF.md).

## What runs today

1. Upload two optical GeoTIFFs with different acquisition dates. The checker
   validates their geospatial metadata and exact pixel-grid compatibility.
2. The deterministic router orders them by date and selects `change_mci_v1`.
3. The main adapter checks the model's narrower input requirements, resolves
   stored files, and calls a local HTTP worker. The main API stays Torch-free.
4. The worker runs the pretrained Change-Agent MCI checkpoint and publishes a
   caption, semantic change mask, statistics, and evidence files.
5. The adapter validates the response and artifacts and writes private source
   provenance. The composer combines the caption and statistics into answer text.
6. The Query Notebook shows Compare, Overlay, and Semantic mask views, measured
   pixel statistics, warnings, a receipt, and downloads through the main API.

The question participates in routing but is not sent to the MCI model. Captions
are pair-level descriptions, not question-conditioned answers. This is not a
general VQA implementation or a model-training pipeline.

## Supported inputs and output meaning

Both files must be exactly **256×256, three-band uint8 RGB optical GeoTIFFs**,
with the same CRS, dimensions, resolution, and affine grid. Both need acquisition
dates, supplied through metadata or the upload form, and the dates must differ.
Upload each separately and submit both returned asset IDs in `POST /query`.

There is no automatic tiling, resizing, resampling, uint16 normalization, or
multiband-to-RGB selection. A compatible geospatial pair can still be rejected
by the model-specific preflight checks.

- Mask classes are unchanged/background, road change, and building change.
- Changed pixels and percentages describe the predicted mask. Connected
  components are regions, not verified building or road instance counts.
- Physical area is included only when validated projected metre-based metadata
  supports it. Geographic coordinates alone do not provide square metres.
- `confidence=0.0` is a compatibility sentinel; the UI says confidence is not
  measured. Captions and masks are model predictions, not calibrated accuracy.
- A zero-change result explicitly says “No detected change.”

## Start the model worker

The main app uses Python 3.12+ and the root `pyproject.toml`. The worker uses a
**separate Python 3.11 environment** and [its pinned manifest](../requirements/tool2-worker.txt).
Run it from the source checkout: `experiments` is not included in the main
package's setuptools package list. Do not install the worker pins into `.venv`.

Create the worker environment once, with Python 3.11 installed:

```powershell
py -3.11 -m venv .venv-mci
.\.venv-mci\Scripts\python.exe -m pip install -r requirements\tool2-worker.txt
```

The official `MCI_model.pth` checkpoint must be supplied separately. It is
Git-ignored and is not downloaded by startup. The recorded CUDA baseline uses
checkpoint SHA-256 `34c6926342c40fdd6d50b43d50257cb46cb6b61763448de9ee551828a64b3eb9`.
The default device is `cuda:0`, requiring a compatible NVIDIA/CUDA runtime.

From the repository root, start the worker in one terminal:

```powershell
.\.venv-mci\Scripts\python.exe -m experiments.tool2_mci.worker_cli `
  --host 127.0.0.1 --port 8012 `
  --checkpoint .\MCI_model.pth `
  --input-root .\runtime\uploads `
  --output-root .\runtime\uploads\tool2-results `
  --device cuda:0
```

Check `Invoke-RestMethod http://127.0.0.1:8012/ready` before querying. Worker
`/health` reports liveness, not model readiness. Start the main API/notebook
in another terminal using [the web README](../apps/web/README.md).

| Main API setting | Default |
|---|---|
| `SATQUERY_MCI_WORKER_URL` | `http://127.0.0.1:8012` |
| `SATQUERY_MCI_CONNECT_TIMEOUT_SECONDS` | `1` |
| `SATQUERY_MCI_ANALYSIS_TIMEOUT_SECONDS` | `15` |
| `SATQUERY_RUNTIME_DIR` | Repository `runtime/uploads` |

If changing the runtime directory, also change the worker's input root to that
directory and output root to its `tool2-results` child. Both processes need the
same local filesystem paths. The browser uses the main API under `/api`, never
port 8012 directly. The combined web server does not start the worker.

## Failures and artifact access

Worker unavailability does not change routing or trigger a stub fallback.

| Condition | Main API behavior |
|---|---|
| Unsupported model input | HTTP 200 rejection envelope, no overlay |
| Worker busy | HTTP 429, `WORKER_BUSY` |
| Worker unavailable / model not ready | HTTP 503 |
| Worker timeout | HTTP 504, `WORKER_TIMEOUT` |
| Invalid worker response / inference failure | HTTP 502 |

The worker has capacity for one analysis at a time and no automatic inference
retry queue. Public Tool 2 evidence is served through
`/artifacts/tool2/{run_id}/{filename}` (prefixed with `/api` in the notebook):
raw and RGB semantic masks, binary mask, overlay PNG, and components JSON.
Private `result.json` and `access.json` are not public downloads.

Artifact access validates the completed result, source provenance, path
containment, and both source assets' retention. Expired or missing sources make
evidence unavailable. These checks are not multi-user authentication; deployment
and remote authenticated workers remain outside the implemented scope.

## Verification

The ordinary main suite uses fake worker responses and requires no checkpoint:

```powershell
.\.venv\Scripts\python.exe -m pytest
npm --prefix apps/web run build
```

Torch is imported only when a checkpoint is actually loaded. Mask statistics,
artifact writing, sample selection, and the in-process worker-contract tests
run in the main environment. Tensor preprocessing and vendored model-class
import skip when Torch is absent. The ordinary suite therefore does not verify
CUDA inference. For frontend-only Tool 2 coverage, run
`node tests/web/verify-tool2.cjs` against the combined server; it exercises the
real UI with mocked API/artifact responses. `node tests/web/verify-live-flow.cjs`
uses the ordinary 64×96 fixtures against the real API: a dated optical pair is
rejected as unsupported Tool 2 input, not as a change stub.

The real shared-app/browser harness requires `.venv-mci`, the checkpoint,
`LEVIR-MCI-dataset/images/test`, CUDA, the built frontend, and browser test
dependencies. With those prerequisites available:

```powershell
$env:RUN_TOOL2_REAL_E2E = '1'
.\.venv\Scripts\python.exe -m pytest tests/tool2_e2e/test_real_e2e.py
Remove-Item Env:RUN_TOOL2_REAL_E2E
```

The handoff's Phase 3B9 records an earlier successful real CUDA run. Its test
GeoTIFFs wrap LEVIR RGB fixtures with synthetic georeferencing, so those results
do not establish geographic accuracy or arbitrary satellite-image support.

Documentation refresh on 2026-09-10: the local main suite passed **230 tests and
98 subtests**, with **8 skipped tests** (Torch/CUDA/checkpoint and one Windows
symlink case). Helper, worker-contract, and analysis tests now run without Torch.
`verify-tool2.cjs` and `verify-live-flow.cjs` passed against the combined server.
The worker environment and checkpoint were absent in this checkout; real model
inference was not rerun.
