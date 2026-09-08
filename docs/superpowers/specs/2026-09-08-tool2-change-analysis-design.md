# Tool 2 Change Analysis Design

## Scope

Build a standalone, reusable bi-temporal change-analysis specialist around the frozen Change-Agent MCI inference baseline. Keep all Torch/model execution inside `experiments/tool2_mci`; do not connect it to SatQuery API, routing, registry, composer, checker, frontend, Tool 1, or Tool 3.

## Architecture

Vendor only the three MCI architecture modules, the 468-token vocabulary, and the upstream MIT license under `experiments/tool2_mci/vendor/change_agent_mci`. The official `MCI_model.pth` remains an external configurable file. The runtime imports only the vendored package, loads the model once, and returns the original caption, semantic class mask, and inference timing.

Pure NumPy/Pillow post-processing converts the mask into validated pixel/class statistics, 8-connected change components, palette and binary masks, an overlay, geospatially honest null physical-area fields, and an uncalibrated-confidence record. `ChangeAnalysisTool` composes these into a dataclass-backed result with JSON-safe dictionaries and artifact paths.

## Invariants

- Phase 1 `test_000004.png` caption and class counts must remain byte-for-byte/numerically identical.
- Classes are 0 unchanged/background, 1 road change, and 2 building change.
- Components are change clusters, never inferred road/building instance counts.
- MCI captions are not question-conditioned; supplied questions are retained only as context.
- Physical area and coordinates remain null without validated projected-metric metadata.
- Confidence score remains null because the model exposes no calibrated overall confidence.
- Every analysis writes to a unique directory and never overwrites prior evidence.

## Verification

Use synthetic masks for unit coverage and keep checkpoint-backed regression separate. Run the vendor runtime against `test_000004.png`, compare its caption, class counts, and raw mask with the frozen Phase 1 artifact, then reuse the loaded runtime for `test_000005.png`, the next lexicographically valid test pair.
