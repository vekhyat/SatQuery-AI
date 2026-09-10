# Tool 2 implementation handoff

## Current status and how to read this log

As of source revision `58d5b51`, Phases 3B1–3B9 are integrated on `main`: `change_mci_v1` is active, public artifacts and deterministic answer composition are implemented, and the notebook has a dedicated change view. Start with [Tool 2 setup and current limitations](TOOL2.md) for day-to-day use.

The sections below are chronological phase records. Statements such as “inactive,” “not implemented,” “next phase,” and phase-specific Git state describe that phase, not the current checkout. Phase 3B9 records the original real CUDA verification; it is historical evidence, not a claim that every machine pulling this repository has the checkpoint or worker installed.

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

## Phase 3B3 — Torch-free main-side MCI client and inactive adapter

### Goal and scope

Phase 3B3 adds the main process’s two Tool 2 boundary components without
activating Tool 2. `change_mci_v1` is implemented and directly tested, but it
is not registered, the router still selects `change_stub_v0`, and the service,
ToolContext, public artifact endpoint, composer, and frontend are untouched.
The main SatQuery process remains Torch-free; MCI architecture, CUDA, vendor
code, and checkpoint loading remain isolated in the worker process.

### Main environment repair

The old main `.venv` was unusable because `pyvenv.cfg` referenced removed
Python 3.12.8. The project declares `requires-python = >=3.12`; the available
Python 3.14.7 therefore satisfies the project constraint without changing it.
Only `.venv` was recreated (never `.venv-mci`) using:

```powershell
$env:UV_CACHE_DIR = (Resolve-Path '.uv-cache-mci')
uv venv --clear --python 3.14 .venv
uv pip install --python .\.venv\Scripts\python.exe -e '.[dev]'
```

The environment is `C:\Users\Aryaveer\Desktop\SIH26167\.venv`, Python
3.14.7, with HTTPX 0.28.1, Pydantic 2.13.5, Rasterio 1.5.1, and pytest 9.1.1.
The first storage-test attempt could not access the sandbox-owned default
pytest temp directory; later pytest runs use a workspace-local `--basetemp`.
This is a test sandbox issue, not a project dependency or source defect.

`httpx>=0.28,<1` was moved from the dev extra into runtime dependencies because
the production synchronous specialist client imports it.

### MCIWorkerClient

`satquery.tools.mci_worker_client.MCIWorkerClient` is a synchronous, normal
main-environment HTTPX client. It imports no Torch, experiments package,
MCIInference, ChangeAnalysisTool, or vendor model code. Its public operations
are `health()`, `ready()`, and `analyze(request)`.

Defaults are loopback `http://127.0.0.1:8012`, 1.0-second connect timeout,
15.0-second analysis read/write timeout, and a 1 MiB maximum response body.
The response cap is intentionally much larger than the bounded JSON contract
while preventing unbounded body parsing. POST analysis has no automatic retry:
a timeout can leave one valid worker run in progress, so retrying could create
duplicate runs.

The client reads responses incrementally up to the byte cap, parses JSON only
after that limit is satisfied, and validates every success through the shared
Pydantic protocol. It also checks that response `request_id` equals the sent
UUID. Transport, timeout, malformed JSON/schema/version, oversized body, and
correlation failures become safe `MCIWorkerClientError` values. Validated worker
errors preserve only their safe code/status/retryability; raw HTTPX exceptions
and raw bodies are not exposed.

### change_mci_v1 adapter

`satquery.tools.change_mci.change_mci_v1` has the normal specialist handler
signature. `build_change_mci_v1(client_factory)` is a small factory used only
to inject a fake client in tests; it avoids a hidden hard-coded network global
without changing ToolContext or registry signatures.

The adapter requires non-null context, `Task.CHANGE`, exactly two distinct plan
asset IDs, both IDs in the supplied AssetRecords, and consistent optional
`before_asset_id`/`after_asset_id` parameters. `plan.ordered_asset_ids` is the
only temporal authority; filenames and dates are never re-sorted.

Input source paths come exclusively from `context.store.source_path(asset)`.
The adapter refuses non-optical input, non-256×256 assets, non-three-band
assets, non-uint8 dtypes, and mismatched CRS/transform/resolution. It does not
resize, tile, convert, or choose bands. The worker remains the final TIFF parser
and format gate.

Geospatial metadata is emitted only when Rasterio can defensibly establish a
projected CRS with metre linear units and finite positive stored resolution. In
that case the worker gets `validated`, CRS, projected status, metre units, and
pixel width/height; otherwise it gets only `{"validated": false}`. The adapter
does not infer units from arbitrary CRS text or fabricate coordinates.

The exact worker request is:

```json
{
  "contract_version": "1.0",
  "request_id": "generated UUID",
  "before_path": "trusted AssetStore path only",
  "after_path": "trusted AssetStore path only",
  "geo_metadata": {"validated": true | false}
}
```

No question, checkpoint, device, output directory, run ID, or model parameter
is sent.

The adapter verifies all advertised artifacts beneath
`context.output_dir/run_id`, then atomically writes private `access.json` with
only source asset IDs, run ID, and `change_mci_v1`. It maps worker filenames to
root-relative URLs such as `/artifacts/tool2/<run_id>/overlay.png`; no
filesystem path is placed in ToolResult. The endpoint that will serve those
URLs does not exist yet.

ToolResult facts contain summary/caption, statistics, both `per_class` and
application-facing `classes`, bounded components, optional physical area and
coordinates, confidence provenance, model/timing, and public artifact URLs.
Overlay type is `change_mask`. Numeric confidence remains `0.0` strictly as a
compatibility sentinel; `confidence_status: not_measured` and provenance explain
that it is not a measured 0% confidence. Sanitized worker warnings are retained
except path-like warning text, and one clear calibration-sentinel warning is
added if absent.

### Tests and defects found

New main-side tests cover validated requests, safe 429/503/transport/timeout
errors, malformed JSON/schema/version, response-size cap, request-ID mismatch,
and proof of one POST attempt. Adapter tests cover plan ordering, trusted source
paths, metadata preflight, geo metadata, artifacts/access manifest, public
URLs, confidence mapping, warnings, missing artifacts, and mismatch rejection.
The import test imports protocol/client/adapter in the main environment and
asserts neither `torch` nor `experiments.tool2_mci` loaded.

Two defects were discovered during test-driven implementation:

* **Symptom:** an oversized-response error caused `FrozenInstanceError` while
  unwinding HTTPX/unittest contexts. **Root cause:** `MCIWorkerClientError` was
  a frozen dataclass, while Python must attach traceback attributes to raised
  exceptions. **Fix:** make the structured exception mutable. **Why correct:**
  it preserves safe fields while restoring normal exception semantics.
* **Symptom:** a fake path-like warning reached ToolResult. **Root cause:** the
  worker protocol validates warning shape, not embedded filesystem text.
  **Fix:** adapter filters Windows/absolute Unix path-like warning strings.
  **Why correct:** worker warnings remain useful while final main results do not
  expose paths.

### Remaining limitations

This adapter is intentionally inactive. No router/registry/service/client
wiring, generic specialist error model, ToolContext expansion, artifact API,
composer, frontend, or broad GeoTIFF preprocessing was implemented. The next
phase is **3B4 only**.

## Phase 3B4 — task-specific specialist execution context

### Goal and ownership

`ToolContext` is the server-owned bundle of trusted execution resources that a
specialist may use: the `AssetStore`, its private output directory, the public
artifact URL base, and the application semaphore. It is built by the service,
not by a specialist, so query text and route parameters cannot invent storage
paths or publication URLs.

The existing `ToolContext` dataclass remains unchanged. Tool 2 does not get a
parallel context class or Tool-2-specific fields. In particular, worker URL,
HTTP client, checkpoint, CUDA device, question text, and model configuration do
not belong in this storage/execution context.

`satquery.tools.context.build_tool_context` now maps supported specialist tasks
to their server-owned layout:

* `Task.CHANGE` uses `<store.root>/tool2-results` and
  `<artifact-root>/tool2`.
* `Task.OPTICAL_SAR` uses `<store.root>/tool3-results` and
  `<artifact-root>/tool3`.

`Task.SINGLE_IMAGE` and `Task.REJECT` have no specialist artifact context and
are rejected explicitly by the builder. The service passes `None` to the Tool
1 stub, preserving its externally visible behavior without inventing a Tool 1
artifact namespace. Change routes receive the prospective Tool 2 context, but
the registry still executes `change_stub_v0`; no worker call is made.

### Tool 3 regression protection

Before Phase 3B4, `SatQueryService.tool_context()` produced:

* `store`: the service's exact `AssetStore` object
* `output_dir`: `<store.root>/tool3-results`
* `artifact_base_url`: `/artifacts/tool3` by default
* `slots`: the service's exact `BoundedSemaphore(1)` object

Those values and object identities are unchanged after Phase 3B4. The
no-argument `service.tool_context()` call remains Tool 3-compatible because the
existing Tool 3 artifact endpoint uses it. Existing integration tests prove
the disk layout, default and `/api`-mounted artifact URLs, access controls,
run publication, and busy/release behavior are unchanged. No Tool 3 source file
was modified.

The service still owns one `BoundedSemaphore(1)`, and Tool 3 still acquires and
releases it inside `optical_sar_v1`. Tool 2's context carries the same field
only because it is part of the unchanged dataclass; `change_mci_v1` does not
acquire it. MCI inference serialization remains exclusively in the isolated
worker's `BoundedSemaphore(1)`. The service does not add a second MCI queue or
GPU concurrency mechanism.

### Artifact-root normalization

The API query route now supplies the shared root (`/artifacts`, or for a
mounted app `/api/artifacts`) rather than a Tool-3-specific URL. The context
builder removes trailing slashes once and appends exactly one task segment.
Thus `/artifacts/` becomes `/artifacts/tool2` or `/artifacts/tool3`, and
`/api/artifacts/` preserves the `/api` mount prefix without a double slash.

Inputs already ending in `/tool2` or `/tool3` are rejected as caller mistakes;
this prevents `/artifacts/tool3/tool3`. This is intentionally a small local
normalization rule rather than a new general URL utility. The public Tool 3
artifact endpoint itself was not changed, and a Tool 2 artifact endpoint still
does not exist.

### Files and tests

Phase 3B4 creates `tests/test_tool_context.py` and modifies only:

* `satquery/tools/context.py`
* `satquery/service.py`
* the query route's shared artifact-root argument in `apps/api/main.py`
* this handoff document

Focused tests cover exact Tool 2 and Tool 3 output paths, default and mounted
URLs, trailing-slash normalization, store/semaphore identity, unsupported
tasks, and protection from an already specialist-suffixed root. Existing Tool
3 team-integration and main API suites provide the behavioral regression
coverage. The main import-boundary test confirms these shared modules still do
not load Torch or `experiments.tool2_mci`. No checkpoint, worker, or PyTorch is
needed for Phase 3B4.

### Problems encountered and exact fixes

* **Symptom:** the first targeted import-boundary command failed before running
  a test. **Root cause:** the command guessed a nonexistent unittest class name;
  the real class is `ChangeMciProtocolTest`. **Fix:** inspect the test module and
  run the exact method selector. **Why correct:** the real import-boundary test
  then passed unchanged; no product code or test semantics were altered.
* **Symptom:** after introducing the builder, the unchanged mounted Tool 3 test
  failed because `service.query` supplied `/api/artifacts/tool3` positionally as
  the new `task` argument. **Root cause:** the pre-3B4 API/service boundary
  passed a final Tool 3 URL, while the approved builder requires a task and a
  shared artifact root. **Fix:** the API supplies `/api/artifacts`, and the
  service supplies `plan.task` plus that root to the builder. **Why correct:**
  task-specific suffixing now has one owner, the mounted Tool 3 URLs return to
  their exact former values, and Tool 2 can receive `/api/artifacts/tool2`
  without special API logic.

### Remaining limitations

Tool 2 remains inactive: the router still selects `change_stub_v0`, the
registry does not contain `change_mci_v1`, and the service makes no MCI HTTP
call. Generic specialist error translation, worker configuration/wiring,
readiness behavior in the main service, and activation belong to **Phase 3B5
only**. Tool 2's public artifact endpoint, composer changes, and frontend work
remain later phases.

## Phase 3B5 — activate the MCI specialist in SatQuery

### What activation means

The deterministic `Task.CHANGE` route now selects `change_mci_v1`. The
application registry contains both the active implementation and the retained
`change_stub_v0` development stub, but routing never consults worker readiness
and never falls back to the stub. A missing, busy, timed-out, or failed worker
therefore remains an explicit infrastructure error instead of being presented
as a successful lower-quality analysis.

The active backend flow is:

```text
upload/checker -> deterministic router -> per-app registry -> change_mci_v1
-> reused MCIWorkerClient -> localhost worker -> ToolResult -> ResultEnvelope
```

The service only handles the shared specialist contract. It does not import an
MCI model, parse worker protocol JSON, make HTTP calls directly, or know Tool 2
caption/statistics details.

### Generic specialist execution errors

`satquery.errors.ToolExecutionError` extends `SatQueryError` with task-neutral
`http_status`, `code`, `message`, `retryable`, `as_rejection`, and optional safe
`details`. It never stores a traceback, exception representation, worker body,
checkpoint path, or source path.

The service catches this one abstraction. If `as_rejection` is true, the error
becomes a rejected `ResultEnvelope` with a tool-stage rejection trace. If false,
it is re-raised through the existing safe `SatQueryError` API handler and
becomes an HTTP `ErrorEnvelope`. Infrastructure failures are never converted
into a semantically successful or user-input rejection result.

The Tool 2 mapping is:

| Code | HTTP | Retryable | Rejection | Meaning |
|---|---:|---:|---:|---|
| `UNSUPPORTED_IMAGE` | 422 | no | yes | user can supply an exact supported TIFF |
| `WORKER_BUSY` | 429 | yes | no | worker capacity is occupied |
| `MODEL_NOT_READY` | 503 | no | no | worker model lifecycle is not ready |
| `WORKER_UNAVAILABLE` | 503 | yes | no | transport cannot reach worker |
| `WORKER_TIMEOUT` | 504 | yes | no | analysis exceeded the configured timeout |
| `INVALID_WORKER_RESPONSE` | 502 | no | no | malformed/mismatched/untrusted worker result |
| `INFERENCE_FAILED` | 502 | no | no | remote inference failed safely |
| `ARTIFACT_WRITE_FAILED` | 502 | no | no | remote artifact publication failed |
| `INPUT_FILE_NOT_FOUND` | 502 | no | no | worker could not see a validated store path |
| `INVALID_REQUEST` | 502 | no | no | worker rejected an internally generated request |
| `WORKER_TRANSPORT_ERROR` | 502 | yes | no | other safe HTTP transport failure |
| `CUDA_OOM` | 503 | no | no | worker GPU memory is insufficient |

Unknown client codes are reduced to `INVALID_WORKER_RESPONSE`. Messages are
fixed application text rather than raw worker or HTTPX exception strings.
Failure to write the main-side private `access.json` is a local
`ARTIFACT_WRITE_FAILED` with HTTP 500.

Tool 2 preflight rejects unsupported 256/three-band/uint8/optical/grid inputs
before constructing a worker call. Invalid plans, missing context, request-ID
mismatch, and missing/unsafe advertised artifacts are infrastructure defects,
not user rejections.

### Tool 3 migration and unchanged behavior

`ToolInputError` now subclasses `ToolExecutionError` with
`as_rejection=True`, while retaining the exact external status 422, code
`tool3_invalid_dataset`, and actionable message. Missing context, busy state,
and Tool 3 raster/output I/O now also use the generic class. Their existing
HTTP statuses, codes, safe messages, disk artifacts, URLs, and semaphore
behavior are unchanged. `artifact_path` continues to use ordinary
`SatQueryError` because artifact retrieval is an API resource operation rather
than specialist execution.

### Worker configuration and lifecycle

`Settings` now supports:

* `SATQUERY_MCI_WORKER_URL` (default `http://127.0.0.1:8012`)
* `SATQUERY_MCI_CONNECT_TIMEOUT_SECONDS` (default `1.0`)
* `SATQUERY_MCI_ANALYSIS_TIMEOUT_SECONDS` (default `15.0`)

`create_app` constructs one Torch-free `MCIWorkerClient` from those values,
binds it into a per-app copy of the registry through the existing adapter
factory, and reuses it for all Tool 2 requests. The client is closed during app
lifespan shutdown. A client explicitly injected for tests is caller-owned and
is not closed by the app. The global `TOOL_REGISTRY` is never mutated, avoiding
cross-app or cross-test contamination. Worker URL, timeouts, HTTP client,
checkpoint, and device remain outside `ToolContext`.

### Registry, routing, service, and trace

The global registry now contains:

* `single_image_stub_v0`
* `change_stub_v0`
* `change_mci_v1`
* `optical_sar_v1`

The router changes only the selected change implementation from
`change_stub_v0` to `change_mci_v1`. Task inference, input compatibility,
acquisition-date ordering, Tool 1, and Tool 3 routing are unchanged. No `/ready`
request is made by the router or service.

`SatQueryService` accepts a registry mapping and invokes every specialist
through the same `execute_tool` call. Stub status comes from the registry's
explicit stub-name set rather than suffix matching. Successful real tools now
use the neutral message `<tool> completed specialist analysis.` and include
`tool`, `facts_returned`, and `overlay_type` in the tool trace. Tool 3's existing
`fusion_rule` trace detail is preserved when that fact exists.

### Question provenance and artifacts

The question continues to influence deterministic routing only. It is absent
from `ChangeAnalysisRequest`, the fake transport records that absence, and the
MCI caption continues to declare `question_conditioned=false`. Tool 2 does not
claim arbitrary VQA behavior.

Successful Tool 2 responses now contain `/artifacts/tool2/<run_id>/...` URLs
and write private `access.json`. Phase 3B5 deliberately adds no Tool 2 GET
route: an integration assertion confirms that fetching the produced overlay
URL still returns 404. Public serving belongs to Phase 3B6.

### Testing

`tests/fake_mci_worker.py` provides a Torch-free `httpx.MockTransport` fixture
that validates the real main-side HTTP client/protocol path and creates the
five advertised files under the test Tool 2 output root. The normal main API
fixture injects this client, so main tests require neither PyTorch, CUDA,
checkpoint, nor `.venv-mci`.

Activation tests cover the complete backend success path, trusted before/after
ordering, question exclusion, ToolResult/ResultEnvelope mapping, access
manifest, safe URLs, the intentional missing public GET route, preflight
rejection without a worker call, 429/502/503/504 infrastructure responses, and
an instrumented proof that unavailable worker execution never invokes the
stub. Separate tests cover error fields/policies, Tool 3 generic-error
migration, environment configuration, owned/injected client lifecycles, and
the expanded Torch-free import boundary.

### Problems encountered and exact fixes

* **Symptom:** the first read-only audit batch did not run. **Root cause:** a
  malformed JavaScript template expression in the tool-output formatter.
  **Fix:** correct the local formatter and rerun the unchanged audit commands.
  **Why correct:** no repository command or file mutation occurred in the
  failed call.
* **Symptom:** the first successful end-to-end backend run failed its caption
  assertion after executing Tool 2 correctly. **Root cause:** the new test
  guessed `new buildings appeared`, while the controlled shared fixture emits
  `a road was constructed`. **Fix:** align the literal assertion with the
  fixture. **Why correct:** the protocol result was already correct; no
  production caption behavior was changed.
* **Symptom:** the first Settings patch could not find its expected context.
  **Root cause:** its patch hunk did not match the file's exact multiline
  formatting. **Fix:** read the narrow current section and reapply against
  exact lines. **Why correct:** the failed patch changed no file, and the
  configuration tests then passed.
* **Symptom:** existing API change-route fixtures were 8x6 and the shared API
  fixture had no worker injection. **Root cause:** those tests were written
  while change routing ended at a stub, before exact MCI preflight mattered.
  **Fix:** make only the change-route fixtures 256x256 and inject the real
  Torch-free client over a fake HTTP transport. **Why correct:** tests now
  exercise the production boundary without weakening MCI validation or loading
  the model.

### Remaining limitations

The Tool 2 browser artifact endpoint is absent, so generated Tool 2 URLs return
404 by design until **Phase 3B6 only**. Composer-specific Tool 2 prose and the
frontend are unchanged. No real shared-app checkpoint request was required in
this phase; the mandatory real end-to-end run remains Phase 3B9. The standalone
worker, protocol, MCI architecture, checkpoint, and `.venv-mci` were not
modified.

## Phase 3B6 — securely serve completed change-analysis artifacts

### Why serving is separate from model execution

The MCI worker writes evidence under the server-owned Tool 2 output root, but
neither worker output nor a URL returned by an adapter grants browser access by
itself. The main API now owns the separate authorization and publication
boundary. It exposes only completed, allowlisted evidence whose two source
uploads are still valid according to `AssetStore` retention semantics. The
worker, worker protocol, MCI model, checkpoint, router, registry, specialist
execution, composer, and frontend remain unchanged.

### Disk and URL layout

Tool 2 output is always resolved from:

```text
<AssetStore.root>/tool2-results/<run_id>/
```

The main API serves it only through:

```text
/artifacts/tool2/<run_id>/<filename>
```

When the API is mounted by `apps.web.server`, the existing root-path-aware
query code produces `/api/artifacts/tool2/...`; the same mounted FastAPI route
serves that URL. No `/api` prefix is duplicated or hardcoded into the adapter.

### Run ID, allowlist, and private files

`satquery.tools.change_mci_artifacts` requires the worker's exact lowercase
run-ID format: `[a-f0-9]{32}`. Empty, uppercase, short/long, whitespace,
period, slash, backslash, and traversal-like values are rejected before path
construction.

The public allowlist is exact:

* `overlay.png`
* `semantic_mask_rgb.png`
* `semantic_mask_raw.png`
* `change_binary_mask.png`
* `components.json`

Everything else is private even if physically present, including `result.json`,
`access.json`, before/after copies, checkpoints, logs, arbitrary PNGs, TIFFs,
and JSON files. The resolver never accepts a client-supplied root or nested
filename.

### Completion and provenance validation

Before serving one allowlisted file, the resolver requires all of the following:

1. The canonical run directory is immediately beneath the canonical Tool 2
   root; symlink/reparse escapes fail containment.
2. The requested file is a regular file immediately beneath that run directory.
3. Private `result.json` exists, parses to an object, declares
   `task: "change_analysis"`, advertises itself, and advertises the requested
   artifact through the worker's exact `evidence` key and canonical path.
4. Private `access.json` exists and has exactly `asset_ids`, `run_id`, and
   `tool`; it must name the same run, `change_mci_v1`, and exactly two distinct
   canonical AssetStore UUID strings.
5. `AssetStore.load()` succeeds for both source IDs. A missing, expired, or
   deleted upload therefore makes old evidence unavailable without deleting the
   evidence itself.

`result.json` and `access.json` are never returned to the browser. They are
read only as private completion/provenance records. Any malformed, missing, or
inconsistent item is reduced to the same safe 404 response, so local paths and
private state do not leak.

### Containment, media types, and headers

Every root, run, private manifest, and artifact path uses canonical
`Path.resolve(strict=True)` checks and parent equality; string-prefix checks are
not used. This prevents root-prefix collisions and catches symlink escapes when
Windows permits their creation. The public route assigns media types from the
allowlist only: PNG evidence is `image/png`, and `components.json` is
`application/json`. Responses include `Cache-Control: no-store` and
`X-Content-Type-Options: nosniff`. Images remain inline-renderable; the JSON
artifact is retrievable without a user-controlled disposition filename.

### Tool 3 comparison

Tool 3's existing `/artifacts/tool3/...` endpoint and resolver were not
modified. Tool 2 follows the same main-API ownership, completed-run, source
lifetime, `FileResponse`, and security-header principles, while adding its own
strict worker run-ID and evidence-manifest contract rather than forcing Tool 3
into a new generic abstraction.

### Tests

`tests/test_tool2_artifact_access.py` covers all five successful artifact
fetches, exact media types and headers, private/unknown files, nested and
encoded traversal attempts, malformed run IDs, malformed/missing access and
completion records, mismatched tool/run identifiers, noncanonical/duplicate
asset IDs, unadvertised or missing evidence, source deletion, root-prefix
collision, and mounted `/api` behavior. A Windows symlink-escape test is
skipped with its exact OS error if the local account cannot create symlinks.

The fake worker writes the same private completion-marker shape the real worker
writes. The end-to-end main test therefore proves upload -> query -> Tool 2
public URLs -> HTTP fetch, including bytes generated by the fake worker, with
no PyTorch, CUDA, checkpoint, or direct filesystem knowledge on the browser
side.

### Problems encountered and exact fixes

* **Symptom:** the new success tests returned 404. **Root cause:** Phase 3B5
  intentionally had no Tool 2 artifact route. **Fix:** add the separate
  allowlisted resolver and main API route. **Why correct:** the red test proved
  the missing public boundary rather than changing MCI execution.
* **Symptom:** the first fake-worker query-to-fetch regression still returned
  404 after the route existed. **Root cause:** the Phase 3B5 fake worker wrote
  evidence files but not the private `result.json` completion marker written by
  the real worker. **Fix:** make the test-only fake write a minimal, structurally
  faithful completion record. **Why correct:** the production worker and its
  protocol are unchanged; the test now exercises the actual publication rule.
* **Symptom:** a first search command for worker evidence had an invalid regular
  expression. **Root cause:** an unescaped bracket in the read-only search.
  **Fix:** rerun the audit with separate literal expressions. **Why correct:**
  no repository file or behavior changed in the failed command.
* **Symptom:** Windows refused the symlink fixture. **Root cause:** the current
  account does not have symlink creation permission. **Fix:** skip only that
  test with the exact platform reason while preserving canonical containment in
  production and covering root-prefix escape. **Why correct:** the suite does
  not claim a symlink test passed when the OS prevented setup.

### Remaining limitations

Composer changes and a dedicated frontend Tool 2 viewer are still outside this
phase. The full real-checkpoint shared-application demonstration remains Phase
3B9. Artifact access is local API access control based on retained upload
provenance; multi-user authentication/authorization is a future application
concern.

## Phase 3B7 — deterministic Tool 2 answer composition

### What the composer does

`compose_answer()` now has one narrow Tool 2 branch for a successful
`Task.CHANGE` plan using `change_mci_v1`. It produces a concise, stable summary
from the already validated `ToolResult.facts`: the semantic caption, changed
pixel count/percentage, optional road/building change percentages, and optional
physical area. It performs no model inference, network call, geospatial
calculation, or question answering.

### Caption ownership and question limitation

`facts.caption.text` is the preferred semantic description; `facts.summary` is
used only when the caption structure is absent. The composer may normalize
sentence casing and terminal punctuation for display, but never changes the
caption's meaning. The MCI caption remains non-question-conditioned. The user
question is not inspected or creatively answered by composition.

### Statistics and formatting

Changed pixels and `changed_percent` are emitted only when those existing facts
are present. Pixel counts use thousands separators and percentages use two
decimal places, while the underlying JSON facts remain unrounded. Road and
building values are read directly from each class's existing
`percent_of_valid_pixels` field; the composer never recomputes a denominator or
substitutes `percent_of_changed_pixels`. The output labels them explicitly as
percentages of valid pixels.

Class 1 and class 2 mean semantic `road change` and `building change`. They do
not reveal whether a feature was constructed, removed, demolished, increased,
or decreased. Only the original MCI caption may contain directional language.
Connected-component counts remain technical facts and are never presented as
object counts.

### No-change, area, and confidence behavior

When `changed_pixels` is zero, the composer emits the caption and the zero
changed-pixel summary, but omits zero-valued road/building lines to keep the
answer natural. `physical_area_m2` and `physical_area_hectares` are included
only when already present and numeric; no area is derived inside the composer
and unavailable area is omitted. The `confidence=0.0` compatibility sentinel
and `confidence_status=not_measured` are never rendered as “0% confidence”.

Missing optional caption, class, area, and timing facts are handled without a
crash and without invented values. Tool 3's existing SAR/optical wording,
Tool 1 stub wording, and rejection envelopes remain unchanged.

### API and tests

The fake-worker integration now verifies upload -> query -> `change_mci_v1` ->
deterministic composer -> `ResultEnvelope` with the formatted Tool 2 answer.
Focused composer tests cover positive change, no change, area present/absent,
confidence sentinel handling, semantic class wording, component non-counting,
missing optional facts, Tool 3 preservation, and rejection preservation. The
existing API and Tool 3 suites provide regression coverage for the unchanged
orchestration behavior.

### Problems encountered and exact fixes

* **Symptom:** the initial composer tests returned the old summary or “not
  connected” fallback. **Root cause:** no Tool 2-specific composition branch
  existed. **Fix:** add a branch keyed to `Task.CHANGE` plus
  `change_mci_v1`. **Why correct:** other tasks continue through their prior
  branches and Tool 2 facts remain the sole source of new prose.
* **Symptom:** one confidence test rejected a valid `2.00%` statistic.
  **Root cause:** the assertion searched for the substring `0%`, which also
  occurs inside `2.00%`. **Fix:** assert specifically against `0% confidence`.
  **Why correct:** the production rule concerns the confidence sentinel, not
  ordinary percentage text.
* **Symptom:** the optional-summary test expected no terminal period.
  **Root cause:** the display formatter intentionally normalizes sentence
  punctuation. **Fix:** align the test with the documented natural-sentence
  output. **Why correct:** source facts are unchanged; only answer presentation
  is normalized.

### Remaining limitations

Tool 2 frontend rendering remains unimplemented. The full real-checkpoint
shared-application CUDA demonstration remains Phase 3B9. No LLM, VQA layer, or
direction-inference heuristic was added.

## Phase 3B8 — dedicated Tool 2 change-analysis frontend view

### Purpose and rendering boundary

`Tool2ChangeView` is a dedicated evidence view for successful real Tool 2
results. It is deliberately not a generic specialist renderer: Tool 3 retains
`Tool3Maps`, and the prior `SceneViewer` remains the fallback for Tool 1,
stubs, rejected results, and incomplete results. App selection is explicit:
`Task.OPTICAL_SAR` plus `optical_sar_v1` renders Tool 3; `Task.CHANGE` plus
`change_mci_v1` and a non-rejected receipt renders Tool 2. This prevents a
similarly shaped response from selecting a specialist view by branch order.

### Evidence modes and legend

The view provides keyboard-accessible Compare, Overlay, and Semantic mask
buttons with a visible selected state. Compare reuses the existing
`SceneViewer` and therefore preserves the already established before/after
ordering and labels. Overlay displays the worker-produced `overlay.png`; the
mask mode displays `semantic_mask_rgb.png` and its text legend. The verified
runtime palette is black for unchanged/background, yellow for road change, and
red for building change. Labels intentionally say only “road change” and
“building change”: mask classes do not establish construction, removal, or
other temporal direction.

### Facts, answer, and confidence

The main answer panel continues to own `answer_text`, warnings, and the
receipt's “Confidence: not measured” presentation. `Tool2ChangeView` adds only
the exact model caption, existing changed pixel/statistic facts, and supplied
physical area facts. It formats counts with separators and percentages to two
decimals, but does not recompute a denominator or derive an area. No-change
results retain the caption, show 0.00% / zero pixels, suppress zero road and
building cards, omit unavailable area, and provide a bounded “No detected
change” status. Component counts are not shown as object counts.

### Artifacts, expiry, and URL safety

The view consumes only the backend-provided artifact values for overlay,
semantic mask, binary mask, and components JSON. It provides downloads for
those public evidence records only; private `result.json` and `access.json`
are never constructed or displayed. A small view-model parser accepts only
canonical root-relative paths, rejecting external, `file:`, protocol-relative,
backslash, query/hash, and traversal-shaped values. It preserves mount-aware
paths such as `/api/artifacts/tool2/...`.

Artifact image errors are tracked per URL. An expired overlay, for example,
becomes a bounded “This evidence item is no longer available” item while the
caption, statistics, downloads, and semantic-mask mode remain usable. The
view does not expose a raw URL or server error. Downloads rely on the secure
artifact endpoint already established in Phase 3B6.

### Accessibility, responsive behavior, and timeout

Images have useful mode-specific alt text, the semantic legend contains both
swatches and text, mode controls are native buttons with `aria-pressed`, and
downloads have labelled links. The layout collapses caption/statistics columns
on narrow screens while retaining usable evidence controls. The frontend query
timeout changed from 15 to 30 seconds to give a real Tool 2 request appropriate
headroom; health (15 seconds) and uploads (120 seconds) are unchanged. This is
only client patience, not a substitute for worker preloading.

### Tests and Tool 3 regression

`tests/web/verify-tool2.cjs` intercepts only the external API/artifact boundary
and exercises the built React notebook: upload/preview flow, real Tool 2
selection, caption, formatting, optional area, confidence sentinel, compare /
overlay / mask modes, legend, public downloads, unsafe URL suppression,
no-change display, Tool 3 specialist selection, Tool 1/rejected fallback, and
a per-artifact expiry without collapsing the view.
`tests/web/verify-tool3.cjs` remains the regression coverage for Tool 3's three
maps, controls, downloads, confidence, and responsive layout.

### Problems encountered and exact fixes

* **Symptom:** the first Tool 2 browser test timed out waiting for a change
  evidence region. **Root cause:** the pre-3B8 app had only Tool 3 specialist
  rendering and otherwise used `SceneViewer`. **Fix:** introduce the narrowly
  eligible `Tool2ChangeView`. **Why correct:** the test proves the user-visible
  missing capability without modifying a backend layer.
* **Symptom:** Playwright's default missing-locator wait left child processes
  active during the red test. **Root cause:** its general default wait was much
  longer than this focused capability check. **Fix:** give the new missing-view
  assertions a five-second explicit timeout and terminate only those test
  processes. **Why correct:** it makes the expected red condition bounded and
  does not alter application behavior.
* **Symptom:** the historic `verify-live-flow.cjs` expected a 64×96 change pair
  to complete through the former change stub. **Root cause:** it predates the
  active Tool 2 MCI gate, which correctly rejects non-256×256 imagery before
  inference. **Fix:** leave that out-of-scope historic script unchanged and
  cover Tool 1/rejection fallback through the new frontend boundary fixture.
  **Why correct:** weakening the real worker's approved input policy merely to
  preserve an obsolete browser fixture would be incorrect.
* **Symptom:** an encoded traversal-shaped artifact URL was normalized by the
  browser URL parser and appeared as a download. **Root cause:** validation
  checked only the normalized pathname. **Fix:** reject raw and decoded `.` /
  `..` / backslash path segments before URL construction, with a browser
  regression assertion. **Why correct:** the frontend now refuses unsafe input
  even before the already-secure backend endpoint receives it.

### Remaining limitations

The UI is backed by the existing secure local artifact service; it does not add
multi-user authorization, a frontend object-count interpretation, a VQA layer,
or any MCI inference behavior. The full real-checkpoint shared-application CUDA
demonstration remains Phase 3B9.

## Phase 3B9 — final real CUDA shared-application verification

### Verified live architecture

The final opt-in harness exercised the real deployed boundaries in sequence:

```text
Browser
  -> SatQuery React frontend
  -> mounted main API (/api)
  -> AssetStore + checker_v1
  -> deterministic router_v1
  -> change_mci_v1
  -> Torch-free MCIWorkerClient
  -> localhost HTTP (127.0.0.1:8012)
  -> production MCI worker
  -> MCIInference + official checkpoint
  -> ChangeAnalysisTool
  -> worker-owned artifacts/result.json
  -> ToolResult
  -> deterministic composer
  -> ResultEnvelope
  -> secure main artifact API
  -> Tool2ChangeView
```

The browser never received or requested the worker URL. It uploaded and queried
only through the mounted SatQuery API and fetched evidence through
`/api/artifacts/tool2/...`. The main Python 3.14.7 process remained Torch-free;
only the Python 3.11.15 worker loaded PyTorch 2.0.1+cu118 and CUDA 11.8.

### Opt-in harness and fixture honesty

`tests/tool2_e2e/test_real_e2e.py` is disabled unless
`RUN_TOOL2_REAL_E2E=1`. It locates the ignored official checkpoint and
LEVIR-MCI data, creates ignored temporary TIFF wrappers, starts the production
worker and combined web/API processes, performs positive and no-change API
queries, fetches public evidence, invokes the real browser verifier, and always
terminates both child processes and removes its temporary directory.

The wrappers are 256×256, three-band, uint8 TIFFs. RGB arrays are written
without resize, stretch, normalization, tiling, band selection, or value
conversion. Decoded TIFF arrays are compared byte-for-byte with their source
PNG arrays. The pixel-byte SHA-256 pairs were identical:

* `test_000004` before:
  `2611bbac502e30de959df95dd2b6225a4dc9f06dcf6386719305220644e56eb8`
* `test_000004` after:
  `6b48d5018ab98242a1007eb531add34ba0cf7c2c9033733aee5b3d7d97f568ad`
* `test_000005` before:
  `951a6972b34f977acb34c2938785d6874480d2f77831527780b0a75379a67cda`
* `test_000005` after:
  `f1f6ea599d0857d9a9dfd16027c5dfab394f8e45be4e50083367ab14b1c9cd42`

The checker requires a CRS and non-identity transform, while LEVIR-MCI carries
no defensible geography. The wrapper therefore declares an explicitly
synthetic test-only EPSG:4326 grid. Because it is geographic rather than a
validated projected metric grid, `change_mci_v1` sends geospatial metadata as
unvalidated and both physical-area facts remain null. No hectare or location
claim is produced.

### Real worker, checkpoint, device, and timings

The worker used the production `experiments.tool2_mci.worker_cli`, bound only to
`127.0.0.1:8012`, with the API upload directory as its input root and the
task-specific `tool2-results` directory as its output root. `/ready` reported:

* contract `1.0`
* model `Change-Agent MCI`
* device `cuda:0`
* vocabulary size `468`
* checkpoint SHA-256
  `34c6926342c40fdd6d50b43d50257cb46cb6b61763448de9ee551828a64b3eb9`

Measured worker process start to ready was `7.8764 s`. With the worker already
ready, the positive main-API query took `0.9473 s`, including model inference
of `0.6306 s`. The no-change API query took `0.1844 s`, including inference of
`0.0763 s`. These are local single-run observations, not performance promises.
They are well below the frontend's 30-second query timeout.

`nvidia-smi` reported 0 MiB used before worker start, 579 MiB once ready, and
793 MiB after both positive and no-change requests. Memory remained 793 MiB
after the second request, with 5,209 MiB free; this shows stable reuse for the
tested sequence rather than runaway allocation. One worker PID served two API
analyses plus both browser analyses, `/ready` remained unchanged, and the
checkpoint initialization occurred once before the server became reachable.

### Frozen positive and no-change results

The real uploaded `test_000004` wrappers routed to exactly
`checker_v1`, `router_v1`, and `change_mci_v1`; the receipt was not rejected,
the tool trace was `ok`, and no stub fallback occurred. The exact result was:

* caption: `the vegetation has been removed and a road with villas built along appears`
* unchanged/background: `45,598`
* road change: `7,382`
* building change: `12,556`
* changed: `19,938` / `30.4229736328125%`
* answer: `The vegetation has been removed and a road with villas built along appears. Changed pixels: 19,938 (30.42% of valid pixels). Road change: 11.26% of valid pixels; building change: 19.16% of valid pixels.`

The public raw-mask PNG SHA-256 was exactly
`b6e9c476be46ecfbdfe074c50c9604fd78d2c528e4fa410c3d99f3ef568953ce`.

The real uploaded `test_000005` wrappers used the same full path and returned:

* caption: `the scene is the same as before`
* unchanged/background: `65,536`
* road change: `0`
* building change: `0`
* changed: `0` / `0%`
* answer: `The scene is the same as before. Changed pixels: 0 (0.00% of valid pixels).`

The real browser rendered “No detected change” and suppressed road/building
zero cards for that actual backend result.

### Real artifacts and security

All evidence was fetched through the main public endpoint, not from disk. For
the positive run, results were:

| Evidence | HTTP | Content-Type | Bytes | Dimensions |
|---|---:|---|---:|---|
| `overlay.png` | 200 | `image/png` | 138,900 | 256×256 |
| `semantic_mask_rgb.png` | 200 | `image/png` | 2,982 | 256×256 |
| `semantic_mask_raw.png` | 200 | `image/png` | 2,368 | 256×256 |
| `change_binary_mask.png` | 200 | `image/png` | 2,299 | 256×256 |
| `components.json` | 200 | `application/json` | 13,303 | valid JSON |

Every public response carried `Cache-Control: no-store` and
`X-Content-Type-Options: nosniff`. Real `result.json` and `access.json` requests
both returned safe 404 responses. The no-change run independently returned 200
for the same five public artifact types and 404 for both private records.

### Real frontend result

`tests/web/verify-tool2-real.cjs` used the built React application with no
network interception or fake result. It uploaded the TIFFs, queried the mounted
main API, selected Compare, Overlay, and Semantic mask, and verified the real
caption, 19,938 / 30.42% statistics, semantic legend, secure download URLs,
deterministic answer, and `Confidence: not measured`. Browser-originated
overlay and RGB-mask requests returned 200. Its captured network list contained
no request to port 8012, checkpoint path, or raw worker endpoint and no page
errors.

### Integration problems and fixes

No production integration defect was found and no production model, worker,
backend, or frontend file required a 3B9 fix. Three harness issues were found:

* **Symptom:** the first run stopped after `/ready`. **Layer:** new E2E harness.
  **Root cause:** its expected dictionary omitted the protocol's existing
  `contract_version`. **Why earlier tests missed it:** the new assertion had not
  existed. **Fix:** assert `contract_version: 1.0` explicitly. **Regression:**
  the opt-in harness now validates the complete readiness payload.
* **Symptom:** the next run reported a raw-mask hash mismatch although the
  displayed strings were otherwise identical. **Layer:** new E2E harness.
  **Root cause:** the expected literal had one extra `e` while transcribing the
  supplied SHA. **Why earlier tests missed it:** existing checkpoint tests use
  decoded array equality rather than this public-file hash literal. **Fix:**
  correct the literal to the supplied hash. **Regression:** the public artifact
  hash assertion now passes exactly.
* **Symptom:** invoking pytest inside `.venv-mci` failed with “No module named
  pytest”. **Layer:** verification command only. **Root cause:** the intentionally
  minimal worker environment contains `unittest` tests but not pytest. **Why
  earlier tests missed it:** prior phases used native unittest invocation.
  **Fix:** run MCI suites with `python -m unittest`; no dependency was added.
  **Regression:** all native MCI suites and both opt-in checkpoint tests passed.

### What is now implemented

The current SIH Tool 2 scope is complete: exact compatible TIFF upload,
validation and temporal ordering, deterministic routing, active
`change_mci_v1`, Torch-free main client, loopback worker isolation, official
CUDA checkpoint inference, semantic caption/mask/statistics, deterministic
composition, private provenance manifests, secure public artifacts, and the
dedicated browser evidence view. Normal tests remain checkpoint- and CUDA-free;
all real verification is explicitly opt-in.

### What is not implemented

The completed scope intentionally excludes arbitrary-size imagery, tiling or
mosaicking, automatic resampling, arbitrary multiband-to-RGB selection, uint16
normalization, a general satellite preprocessing pipeline, question-conditioned
VQA, LLM interpretation, calibrated confidence, object-instance counting,
remote authenticated workers, multi-user authorization, and training or
fine-tuning. These are explicit non-goals, not claims made by the current tool.

### Final current-scope acceptance

All mandatory current-scope checks passed with direct evidence:

* official checkpoint loaded and `/ready` reported real CUDA
* faithful 256×256 RGB uint8 TIFF wrappers uploaded through the main API
* checker accepted both pairs and router selected `change_mci_v1`
* no stub fallback and main imports remained Torch-free
* positive caption, all three class counts, changed count/percentage, and raw
  mask SHA matched the frozen baseline exactly
* all five public artifacts returned 200 with their expected type, dimensions,
  and security headers; both private artifacts returned 404
* deterministic positive and no-change composer text matched exactly
* `confidence=0.0` remained a sentinel and the UI displayed “not measured”
* real Tool2ChangeView compare, overlay, mask, caption, statistics, legend,
  downloads, receipt, answer, and no-change behavior were browser-exercised
* Tool 3, Tool 1/rejection fallback, normal checkpoint-free suites, opt-in
  checkpoint suites, and the production frontend build passed
* worker, web/API, browser, and temporary fixture processes/data were cleaned;
  ports 8012 and 5173 were free and GPU memory returned to 0 MiB afterward

Verification counts were: 189 passed / 2 expected skips / 87 subtests in the
main suite; 7 MCI inference/vendor tests; 20 worker tests with 2 expected skips
in the non-opt-in run; 1 standalone checkpoint test; 1 real worker HTTP
checkpoint test; 1 real shared-app/browser E2E test; and both Tool 2 and Tool 3
browser scripts. The Vite/TypeScript production build completed successfully.

### Reproducible local startup

From the repository root, start the model worker in one PowerShell window:

```powershell
.\.venv-mci\Scripts\python.exe -m experiments.tool2_mci.worker_cli `
  --host 127.0.0.1 --port 8012 `
  --checkpoint .\MCI_model.pth `
  --input-root .\runtime\uploads `
  --output-root .\runtime\uploads\tool2-results `
  --device cuda:0
```

Verify readiness with `Invoke-RestMethod http://127.0.0.1:8012/ready`. Build and
start the combined frontend/main API in another PowerShell window:

```powershell
$env:SATQUERY_MCI_WORKER_URL = 'http://127.0.0.1:8012'
npm --prefix apps/web run build
.\.venv\Scripts\python.exe apps\web\server.py --port 5173
```

Open `http://127.0.0.1:5173`. The main API is mounted under `/api`; the browser
must never be configured with or sent directly to the worker URL.
