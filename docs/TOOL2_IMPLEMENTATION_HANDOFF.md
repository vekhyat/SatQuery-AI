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

## Phase 3B2 — adversarial hardening and worker verification

### Goal and scope

Phase 3B2 hardened the already-implemented worker boundary. It added no main
SatQuery client, adapter, registry/router/service change, artifact endpoint,
composer, or frontend work. The only production behavior tightened is the
worker's input and public-artifact policy.

Before the phase, the complete Phase 3B1 file set was verified, committed
locally as `f3400a3 tool2: add isolated MCI worker protocol and API`, and
anchored at `backup/tool2-after-3b1`. Nothing was pushed.

### What changed

* The shared Pydantic protocol now rejects NaN/infinite values, rejects a
  changed-pixel count greater than valid pixels, and requires changed plus
  unchanged pixels to equal valid pixels. These are small transport invariants,
  not an attempt to duplicate the standalone analysis engine.
* Public artifact fields now contain only `semantic_mask_raw.png`,
  `semantic_mask_rgb.png`, `change_binary_mask.png`, `overlay.png`, and
  `components.json`. The worker still validates all internally created evidence
  under its run directory, including `before.png`, `after.png`, and
  `result.json`, but does not advertise those internal files.
* The production worker now accepts only readable TIFF files with `.tif` or
  `.tiff` suffixes that are exactly 256×256, RGB, three-channel, and explicitly
  report 8 bits per sample. It rejects PNG, dimensions other than 256×256,
  grayscale, RGBA/multiband, uint16, corrupt TIFFs, and extension/content
  mismatches. It does not resize, stretch, guess band ordering, or convert
  uint16 imagery.
* `ImagePolicy.INTERNAL_LEVIR_PNG_REGRESSION` is an explicitly test-only path
  used only by `experiments.tool2_mci.tests.checkpoint_worker_server`. The
  production CLI and ordinary `create_app` default to `PRODUCTION_TIFF`.
  This permits the frozen LEVIR PNG checkpoint regression without weakening the
  future shared-app GeoTIFF boundary.
* Loopback process tests use a separate fake-worker process and an ephemeral
  port. They confirm `127.0.0.1` behavior, no CORS header, health/readiness,
  ready analysis, and live-but-not-ready STARTING/FAILED states. Test teardown
  terminates every spawned worker process.

### Security and correctness verification

Protocol adversarial tests now cover missing/wrong contract version, malformed
UUID, missing/relative/empty paths, non-object geospatial metadata, strict
unknown fields, malformed success and error payloads, invalid run IDs, absolute
or traversing artifact fields, path separators, negative counts, count
inconsistency, changed fractions/percentages out of range, and NaN/Infinity.

Path tests use temporary Windows roots and canonical `Path.resolve` plus
`relative_to`, never string prefixes. They cover valid containment, sibling
roots, nested traversal, `uploads` versus `uploads-evil` prefix collision,
directories, missing files, and artifact escape. The symlink escape test is
present but skipped on this machine with documented Windows error 1314 because
the process lacks the SeCreateSymbolicLink privilege; it is not reported as a
pass. Junction/reparse-point creation was not available under the same policy.

Run IDs are worker-created lowercase 32-hex UUID values. Tests confirm separate
requests receive distinct IDs, users cannot submit a client run-ID field due to
strict request validation, and run directories remain below output_root.

The semaphore remains capacity one. A blocking fake proves the second request
waits only the configured short interval and returns `429 WORKER_BUSY` with
`retryable: true`; the first then completes and a third request succeeds. A
fake exception also proves the `finally` release allows the next request to
succeed. Sensitive failure text containing a local user path, checkpoint name,
CUDA text, traceback text, and a synthetic secret was absent from returned JSON.
Server logs retain diagnostic traces by design.

The worker response preserves component counts and largest-component statistics
but maps at most 10 component items per group. The full component list remains
in internal `components.json`; it is not expanded into the HTTP response.

### Real verification

The actual production CLI was launched hidden on an ephemeral loopback port
using `.venv-mci`, the official checkpoint, `cuda:0`, and the normal TIFF
policy. It returned `/health` with `satquery-mci-worker`, then `/ready` with
`Change-Agent MCI`, `cuda:0`, vocabulary 468, and SHA-256
`34c6926342c40fdd6d50b43d50257cb46cb6b61763448de9ee551828a64b3eb9`. The
process was stopped in the verification command.

One opt-in real worker HTTP analysis was run through the test-only internal
LEVIR PNG policy for `test_000004`. It passed in 10.002 seconds and exactly
matched the frozen result:

* caption: `the vegetation has been removed and a road with villas built along appears`
* class 0: 45598; road class 1: 7382; building class 2: 12556
* changed pixels: 19938

The pre-existing direct opt-in frozen checkpoint regression was also run and
passed in 9.476 seconds. It emitted two upstream deprecation warnings from
timm/Torch; no model, vendor, or checkpoint code was changed.

### Dependency reproducibility

`requirements/tool2-worker.txt` remains the actual minimal worker manifest:
Python 3.11, the verified `torch==2.0.1+cu118` and
`torchvision==0.15.2+cu118` stack, NumPy, Pillow, timm, einops, FastAPI,
Pydantic, Uvicorn, and HTTPX. The file includes the PyTorch cu118 index. A
reproducible command that preserves the existing isolated interpreter is:

```powershell
$env:UV_CACHE_DIR = (Resolve-Path '.uv-cache-mci')
uv pip install --python .\.venv-mci\Scripts\python.exe -r requirements\tool2-worker.txt
```

The installed worker environment was verified as Python 3.11.15, Torch
2.0.1+cu118, torchvision 0.15.2+cu118, NumPy 1.25.2, Pillow 10.0.1, timm
0.9.12, einops 0.7.0, FastAPI 0.141.1, Pydantic 2.13.5, Uvicorn 0.52.4, and
HTTPX 0.28.1. The stale main `.venv`, which points to a removed Python 3.12,
was deliberately not repaired or recreated.

### Files changed in Phase 3B2

* `satquery/tools/change_mci_protocol.py`
* `experiments/tool2_mci/worker_api.py`
* `experiments/tool2_mci/tests/test_worker_api.py`
* `tests/test_change_mci_protocol.py`
* `experiments/tool2_mci/tests/test_worker_hardening.py` (new)
* `experiments/tool2_mci/tests/fake_worker_server.py` (new)
* `experiments/tool2_mci/tests/test_worker_process.py` (new)
* `experiments/tool2_mci/tests/checkpoint_worker_server.py` (new)
* `experiments/tool2_mci/tests/test_worker_checkpoint_http.py` (new)
* this handoff document

### Problems encountered and exact fixes

* **Symptom:** production worker accepted a valid 256×256 PNG and advertised
  internal result/input copies. **Root cause:** the 3B1 image check was generic
  Pillow RGB/size validation and its artifact model represented every internal
  evidence file. **Fix:** strict TIFF/tag validation plus a separate public
  five-file allowlist. **Why correct:** it matches the shared-app GeoTIFF
  contract while preserving standalone PNG and internal evidence behavior.
* **Symptom:** protocol permitted changed pixels above valid pixels. **Root
  cause:** field ranges did not express cross-field consistency. **Fix:** a
  small Pydantic after-validator. **Why correct:** it rejects impossible output
  without taking responsibility for full semantic analysis validation.
* **Symptom:** real-process test initially had no server module. **Root cause:**
  the test was intentionally written before its test-only harness. **Fix:**
  added a deterministic fake-worker Uvicorn module. **Why correct:** it tests
  socket/process behavior without loading CUDA or the checkpoint.
* **Symptom:** a generated footer typo was caught before harness execution.
  **Root cause:** a malformed test-helper line. **Fix:** corrected that one
  line before the green test run. **Why correct:** it changed no production
  boundary.

### Remaining limitations

There is still no main-worker client, Tool 2 adapter, routing, registry,
service integration, public artifact endpoint, GeoTIFF tiling, CORS/auth layer,
warm-up benchmark, composer, frontend, or end-to-end shared application path.
The strict TIFF policy validates format shape and RGB interpretation only; it
does not yet validate geospatial alignment or transform metadata, which remains
the upstream validator's responsibility. The next phase is **3B3 only**.
