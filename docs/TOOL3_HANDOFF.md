# M6 Tool 3: repository integration

Tool 3 is connected to this repository's existing checker, registry, composer, API and Query Notebook. Code lives under `satquery/tools/`, documentation under `docs/`, and the Pack C recipe under `demo/packs/C/`, following the handbook layout. The original integration targeted repository base `4b01f1c`; subsequent shared-service changes use the task-specific `ToolContext` described below.

The implemented models in **`satquery/contracts.py`** remain authoritative. They differ from the earlier handbook sketch: they include a trace and do not define top-level `layers`. No replacement schema or second main API is needed.

## Run from the repository root

Use Python 3.12+ as required by the existing repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m satquery.tools.tool3.pack_c demo/packs/C/generated
npm --prefix apps/web ci
npm --prefix apps/web run build
.\.venv\Scripts\python.exe apps/web/server.py
```

Open `http://127.0.0.1:5173`, start a new investigation, and attach `demo/packs/C/generated/optical.tif` and `sar.tif`. Ask:

> Use the optical and SAR images together to identify built-up and water-covered regions.

The notebook displays **Optical-only / SAR-only / Fused** candidate maps, pixel counts, the measured SAR contribution, warnings, a processing receipt and JSON downloads. Pack C is generated numeric test data, not real satellite imagery or an accuracy benchmark. The generator refuses to overwrite an existing directory.

The normal backend-only startup also works: `python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000`. Its routes have no `/api` prefix; the combined notebook mounts them under `/api`. The returned artifact URLs account for this automatically.

## M3: input requirements

The current shared upload/query API accepts **one optical stack and one SAR stack**, both GeoTIFFs. Its existing checker still requires the same CRS, dimensions and affine grid before routing. Prepare/reproject real sensor products before using this API. The independent Tool 3 manifest interface described below can align compatible source bands itself.

| Stack | Required band descriptions | Optional descriptions |
|---|---|---|
| Optical | `green`, `nir`, `swir` (aliases B03, B08, B11) | `red`, `blue`, `scl`, `valid_mask` |
| SAR | `vv` | `vh` |

Descriptions select one-based band indexes; no positional order is guessed. SAR GeoTIFF band units must identify calibrated `linear` power or `db`. Calibration scale/offset and nodata come from raster metadata. A three-band RGB image lacks NIR/SWIR and is rejected. HH/HV, complex SLC, uncalibrated DN and screenshots are not substitutes for the supported measurements.

Use compatible optical reflectance. Supply optical cloud/quality masks where available. Date hints from upload are checked for the default maximum 30-day gap; embedded dates are also checked by the core. Missing dates are reported as warnings. File paths come from the server's asset store, never from the question or client-supplied paths.

## M1: registry, result and composition

```python
from satquery.tools.optical_sar import optical_sar_v1

# Already registered in satquery/registry.py:
TOOL_REGISTRY["optical_sar_v1"] = optical_sar_v1
```

The handler takes `assets: list[AssetRecord]`, `plan: RoutePlan`, and a server-owned `ToolContext`, then returns the existing **`ToolResult`**. `SatQueryService` supplies storage, output directory, artifact URL prefix and a shared worker slot through this context. The stub handlers accept the context too. Single-image routing remains a stub; temporal change now selects `change_mci_v1` with its own output directory and isolated model worker (see [Tool 2](TOOL2.md)).

Tool 3 returns only `facts`, `confidence`, `warnings`, and `overlay`. The composer writes the answer from `facts.sar_contribution`. The service writes the receipt and includes the fusion rule in its tool trace. Successful Tool 3 traces say `ok`; unsupported bands/units/pixels produce `task="reject"` and a rejected tool trace. Invalid HTTP requests and storage failures retain the repository's existing `ErrorEnvelope` behavior.

| Field | Meaning |
|---|---|
| `facts.layer_urls.optical_only`, `.sar_only`, `.fused` | Three directly fetchable PNG URLs |
| `facts.layers` | Per-map pixel counts, percentages and projected grid area estimates |
| `facts.sar_contribution` | Measured sentence describing what SAR added |
| `facts.fused_differs_from_optical` | Actual comparison; identical outputs are allowed and reported honestly |
| `facts.artifacts` | Artifact-name to URL mapping, including `fused.tif` and index rasters |
| `facts.fusion_rule` | Water-first class union rule used for this result |
| `facts.reference_grid` | CRS, affine transform, dimensions and bounds |
| `facts.processing_parameters`, `facts.software` | Settings and runtime versions |
| `facts.confidence_status` | Explicitly uncalibrated status |
| `overlay` | Existing `heatmap` type with the fused candidate PNG URL |

`confidence=0.0` is an uncalibrated contract placeholder. The UI displays **Confidence: not measured**. Counts and SAR additions describe the generated masks; neither confidence nor sensor agreement is measured classification accuracy.

## M2: displaying results and downloads

The new `Tool3Maps` component reads `facts.layer_urls` without changing the shared TypeScript envelope. Its three buttons select actual computed maps rather than blending the uploaded previews. It updates class counts and handles unavailable/expired images. It is shown only for a successful live optical/SAR result; demonstrations, other tasks and rejected results keep the existing scene viewer.

Class codes: 0 other/unclassified, 1 water candidate, 2 built-up candidate, 255 nodata. PNG colors: dark gray, blue, coral, transparent nodata. Use GeoTIFFs for GIS placement; PNGs share pixel coordinates but do not carry their own georeferencing.

`GET /artifacts/tool3/{run_id}/{filename}` serves only recognized PNG/TIFF artifacts of complete runs. Private `result.json`, `access.json`, `report.html` and source rasters are excluded. Artifact access also checks that both source uploads still exist and have not expired. Local result folders remain on disk for inspection; remove obsolete runs through the team's retention policy when disk reclamation is needed.

Only one Tool 3 request is processed at a time per API process. Concurrent requests receive HTTP 429 `tool3_busy`; retry after the current job finishes. Every successful request creates a new run. The server uses the core's 16-million-pixel limit per source. External deployment, authentication and persistent job scheduling remain responsibilities of the shared app.

## Independent manifest / batch / evaluation use

The core remains importable under `satquery.tools.tool3` and can process explicit paths without the two-upload restriction:

```powershell
python -m satquery.tools.tool3 --manifest path/to/manifest.json --check-only --json
python -m satquery.tools.tool3 --manifest path/to/manifest.json --output-dir runtime/tool3 --open-report
python -m satquery.tools.tool3 --batch path/to/batch.json --output-dir runtime/tool3
tool3-evaluate --prediction runtime/tool3/RUN_ID/fused.tif --reference labels/reference.tif
```

The standalone manifest envelope is internal to this core and its offline report. Its JSON schema files are packaged with the core; they do not replace the team's Pydantic models. Real satellite accuracy requires independent reference labels and representative sensor validation. Refer to `TOOL3_ALGORITHM.md` for full preprocessing/configuration details.

## Verify the integration

```powershell
python -m pytest
python -m pip check
npm --prefix apps/web run build
```

For the browser check, generate Pack C and start the combined server, then run `node tests/web/verify-tool3.cjs`. It defaults to locally installed Microsoft Edge in headless mode; set `PLAYWRIGHT_CHANNEL` for another installed Playwright channel and `SATQUERY_TEST_URL` for a different local port.

The Tool 3 integration is already on `main`. The commands above verify the current
checkout; they are not instructions to replace shared modules or re-submit the
original handoff. Generated imagery, runtime results, environments, and build
outputs remain Git-ignored. The dated acceptance record is in
[Tool 3 validation](TOOL3_VALIDATION.md).
