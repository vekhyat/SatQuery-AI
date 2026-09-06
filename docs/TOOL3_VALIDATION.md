# Tool 3 integration verification

## Local merge verification, 2026-09-06

Rechecked the integrated branch at `573b7bb` in the Desktop checkout. The first
suite run exposed an intermittent Windows `PermissionError` when renaming a
completed temporary run directory. Publication now retries that operation up to
eight times with bounded delays. Two API regression tests verify recovery from
a temporary lock and cleanup plus worker release after a persistent failure.

- Full suite after the fix: **108 tests and 46 subtests passed** (8.70 seconds).
- `python -m pip check`: no broken requirements.
- TypeScript/Vite production build and Python source/wheel builds passed.
- Both `verify-tool3.cjs` and `verify-live-flow.cjs` passed against the combined
  server on port 5183 after restarting it with the fix. Tool 3 uploads, three map
  tabs, counts, confidence text, existing routes, rejections, previews and receipt
  exports were checked. No browser JavaScript errors were reported.
- Desktop and 390-pixel mobile screenshots were inspected; the mobile page had
  no horizontal overflow. Evidence is saved locally under `runtime/` as
  `tool3-browser-desktop.png`, `tool3-browser-desktop-mobile.png` and the matching
  JSON result. Generated artifacts are ignored by Git.

These checks use synthetic fixtures and verify software behavior, not accuracy
on real satellite observations. Dependency deprecation warnings remain.

## Original handoff verification

Verified locally on 2026-09-06 against team repository base `4b01f1c`.

- **106 Python tests passed**, including the existing API/storage/preview suite, core raster tests, and real shared-contract integration tests. Pytest additionally reported 46 passing subtests.
- Validated the existing Pydantic `ToolResult` and `ResultEnvelope` with actual computed results. No shared-model changes were required.
- Exercised upload, checker, router, `optical_sar_v1`, composer, receipt, PNG/GeoTIFF downloads, mounted `/api` URLs, input rejections, worker limits and expired-asset access.
- The frontend TypeScript/Vite production build passed.
- Built the repository wheel, checked that templates/schemas are included and imagery/build caches are excluded, then installed it outside the checkout and verified upload/query plus all three map downloads.
- The existing live browser flow also passed for single-image/change stubs, missing-band rejection and incompatible-grid rejection; previews and receipt downloads continued to work.
- A real headless Edge browser uploaded Pack C through the notebook, selected all three generated maps, checked updated counts and uncalibrated confidence text, and rendered desktop/mobile layouts without JavaScript errors or mobile horizontal overflow.
- Fixed and regression-tested an intermittent Windows file-sharing error when concurrent runs update `latest.json`.

The synthetic API fixture produced 100 fused water-candidate pixels and 182 fused built-up-candidate pixels under default filtering. SAR added 36 water-candidate pixels and 110 built-up-candidate pixels. These are software-fixture observations, not real satellite accuracy.

The unchanged classification core was previously tested on the supplied real scene: all 14 GeoTIFF artifacts validated and input hashes were unchanged. That standalone scene produced 22,800 changed pixels compared with optical-only output. The two-upload API was validated here using named, aligned synthetic stacks; a real API deployment must supply compatible named/calibrated stacks.

Runtime used: Windows, Python 3.14.7, NumPy 2.5.2, Rasterio 1.5.1, OpenCV headless 5.0.0.93, Pillow 12.3.0, FastAPI 0.141.1, Pydantic 2.13.5. The repository requires Python 3.12+; Windows/Linux Python 3.12 CI is configured but has not run on GitHub during local preparation.

Tool 3 remains a deterministic threshold baseline with uncalibrated confidence. Real-world accuracy, hidden-sensor compatibility and system-wide SIH/model requirements are not established by these software checks. No code was uploaded or deployed during preparation.
