# Tool 2 implementation handoff

## Phase 3B1 — isolated MCI worker protocol and API boundary

### Goal and status

Phase 3B1 establishes the local worker boundary around the frozen standalone
Change-Agent MCI runtime. It is complete as an isolated worker-only slice. It
does **not** connect Tool 2 to the SatQuery API, router, registry, composer,
frontend, or public artifact serving.

The phase creates a versioned HTTP contract, a local-only FastAPI worker,
lifecycle/readiness state, one-at-a-time request handling, path containment,
and checkpoint-free API tests. The standalone MCI inference wrapper,
Change-Agent vendor code, checkpoint, and prediction logic were not modified.

### Architecture implemented

```text
future trusted main API/client
          | localhost HTTP, contract 1.0
          v
MCI worker (127.0.0.1:8012 by default)
  ├─ /health       process liveness only
  ├─ /ready        frozen MCI initialization state
  └─ /v1/change-analysis
       ├─ validates trusted server paths under input_root
       ├─ permits one analysis at a time
       ├─ calls injected ChangeAnalysisTool-compatible analyzer
       └─ returns a sanitized response with filenames only
                 |
                 v
      frozen MCIInference + ChangeAnalysisTool (production only)
```

The separation keeps PyTorch, CUDA, the checkpoint, and the Change-Agent
implementation out of the main SatQuery environment. HTTP is the chosen
boundary because the model remains in its verified Python 3.11/CUDA environment
while the future main service uses a stable, versioned data contract. The
browser will not contact this worker directly.

### Files created and responsibilities

* `satquery/tools/change_mci_protocol.py` — Torch-free Pydantic contract 1.0.
  It defines health, readiness, request, success/error, statistics, component,
  artifact, timing, confidence, and model-metadata representations. It rejects
  unrecognized fields and path-bearing artifact values.
* `experiments/tool2_mci/worker_api.py` — FastAPI app factory, trusted-worker
  configuration, lifecycle state, narrow injected analyzer interface, safe
  response mapping, image/path validation, artifact containment, concurrency
  gate, and lazy production MCI initialization hook.
* `experiments/tool2_mci/worker_cli.py` — `python -m` CLI with server-owned
  host, port, checkpoint, input root, output root, and explicit device flags.
* `experiments/tool2_mci/tests/__init__.py` and
  `experiments/tool2_mci/tests/test_worker_api.py` — checkpoint-free focused
  worker tests using a deterministic `ChangeAnalysisTool`-shaped fake.
* `requirements/tool2-worker.txt` — reproducible Python 3.11 worker manifest:
  frozen MCI packages plus FastAPI, Pydantic, Uvicorn, and the test client.
* `tests/test_change_mci_protocol.py` — shared-contract/import-boundary tests.

No pre-existing source file was modified. In particular, `mci_inference.py`,
`change_analysis_tool.py`, vendor model files, `apps/api/main.py`, router,
registry, service, ToolContext, Tool 3, and web files remain untouched.

### Protocol and endpoints

The literal protocol version is `1.0`; this makes future worker/client drift
explicit instead of relying on untyped JSON.

* `GET /health` returns HTTP 200 while the process is alive:
  `{"status":"ok","service":"satquery-mci-worker","contract_version":"1.0"}`.
  It deliberately does not claim the model is ready.
* `GET /ready` returns HTTP 200 only in `READY`, with model name, device,
  checkpoint SHA-256, and `vocab_size: 468`. `STARTING` and `FAILED` return
  HTTP 503, `status: not_ready`, and safe `MODEL_NOT_READY` information.
* `POST /v1/change-analysis` accepts only contract version, UUID request ID,
  absolute before/after server paths, and optional geospatial metadata. It has
  no question, checkpoint, device, model parameter, or output-directory field.
  The worker creates the 32-hex-character run ID.

Success responses echo the request UUID and contain caption provenance,
pixel/class statistics, bounded top component summaries, geospatial values,
confidence provenance, timing, model metadata, warnings, and exact evidence
filenames. They never contain input paths, checkpoint paths, state-dict
details, tracebacks, or artifact absolute paths. Evidence names are the
existing standalone files: `before.png`, `after.png`, `semantic_mask_raw.png`,
`semantic_mask_rgb.png`, `change_binary_mask.png`, `overlay.png`,
`components.json`, and `result.json`.

### Lifecycle and fake runtime design

`WorkerState` tracks only `STARTING`, `READY`, and `FAILED`. `mark_ready`
receives a narrow `ChangeAnalyzer` protocol implementation and safe readiness
metadata. Production initialization lazily imports `MCIInference` and
`ChangeAnalysisTool`, loads the configured checkpoint once, and marks the
state ready. On failure it logs the detail on the worker side and exposes only
`MODEL_NOT_READY`; the HTTP process can remain alive.

The app factory takes `WorkerState`; it never initializes MCI itself. Focused
tests use a deterministic fake analyzer, so ordinary API tests require neither
CUDA, PyTorch model initialization, nor the checkpoint. This is why the frozen
standalone runtime does not need alteration for the worker boundary.

### Security, correctness, and concurrency

Inputs are resolved with `strict=True`, must be existing files, and must be
descendants of resolved `input_root`. This rejects traversal and detectable
symlink escapes. Both must be readable 256×256 RGB images before the analyzer
runs, matching the frozen MCI Phase 1 input requirement.

The worker owns `output_root` and run ID creation. Before serialization every
evidence file is resolved, must be directly inside the worker-owned run
directory under `output_root`, and must have its expected filename. Responses
therefore provide filenames only and cannot leak arbitrary absolute artifacts.

`threading.BoundedSemaphore(1)` gives capacity one. Requests wait only the
configured short interval (0.25 seconds by default); another request receives
HTTP 429 `WORKER_BUSY` with `retryable: true`. No automatic model or inference
retry exists.

Externally safe errors are `MODEL_NOT_READY`, `WORKER_BUSY`,
`INVALID_REQUEST`, `INPUT_FILE_NOT_FOUND`, `UNSUPPORTED_IMAGE`,
`INFERENCE_FAILED`, and `ARTIFACT_WRITE_FAILED`. Internal logs retain
diagnostic tracebacks, while HTTP messages are fixed and path-free.

### Tests and verification

Focused worker tests cover liveness independent of readiness; ready/starting/
failed states; request version and UUID rejection; fake success mapping and ID
echo; filename-only artifacts; missing/outside-root paths; unreadable images;
escaped artifacts; exception sanitization; and busy behavior. The shared
protocol test verifies no Torch import plus request/artifact validation.

Successful commands:

```powershell
& .\.venv-mci\Scripts\python.exe -m unittest tests.test_tool2_change_tool experiments.tool2_mci.tests.test_worker_api
& .\.venv-mci\Scripts\python.exe -m py_compile satquery\tools\change_mci_protocol.py experiments\tool2_mci\worker_api.py experiments\tool2_mci\worker_cli.py
python -c "import sys; import satquery.tools.change_mci_protocol as p; print(p.CONTRACT_VERSION); print('torch' in sys.modules)"
```

The combined standalone/worker command passed 14 tests. The global Python
3.14 import check printed `1.0` and `False` for the Torch import test.

Limited real-runtime verification completed without inference: production
initialization loaded official `MCI_model.pth` through frozen `MCIInference` on
`cuda:0`; `GET /ready` returned HTTP 200 with model `Change-Agent MCI`,
vocabulary size 468, and checkpoint SHA-256
`34c6926342c40fdd6d50b43d50257cb46cb6b61763448de9ee551828a64b3eb9`.

### Problems, root causes, and fixes

* The pre-existing main `.venv` launcher references a removed Python 3.12
  executable. It was not rebuilt because that is outside this worker-only
  scope. The import boundary was additionally verified with global Python 3.14
  and the healthy isolated MCI Python 3.11 environment ran worker tests.
* `.venv-mci` initially lacked FastAPI. The minimal manifest packages were
  installed with `uv`; frozen Torch/CUDA pins were retained.
* The first fake result used keys different from the existing standalone
  `ChangeAnalysisTool` serialization. The fixture was corrected to mirror the
  real boundary rather than changing frozen Tool 2 code.
* An eagerly evaluated fallback for a legacy component configuration raised a
  `KeyError` when the current `minimum_component_pixels` field was present.
  An explicit conditional supports the current boundary and narrow legacy
  fallback correctly.

### Remaining limitations and Git state

No model warm-up, inference benchmark, retry queue, authentication, CORS,
public artifact serving, GeoTIFF tiling, or main-service client is implemented.
Geospatial metadata is passed to the existing standalone tool but is not
independently revalidated here. The worker is local-only and defaults to
loopback. No commit, merge, push, or remote branch modification was performed.

The next implementation phase is **3B2 only**. It must build on this boundary
without beginning main-app integration in Phase 3B1.
