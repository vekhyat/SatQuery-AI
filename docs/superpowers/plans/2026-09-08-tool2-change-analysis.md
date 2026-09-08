# Tool 2 Change Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the standalone Phase 2 Tool 2 analysis layer while preserving the frozen MCI checkpoint prediction.

**Architecture:** The existing `MCIInference` wrapper will import a minimal vendored copy of the research architecture and vocabulary. Pure post-processing modules will compute statistics/components and write evidence; `ChangeAnalysisTool` will return a stable dataclass-backed JSON result without importing into SatQuery.

**Tech Stack:** Python 3.11, PyTorch 2.0.1+cu118, NumPy 1.25.2, Pillow 10.0.1, timm 0.9.12, einops 0.7.0, unittest.

**Spec:** `docs/superpowers/specs/2026-09-08-tool2-change-analysis-design.md`

## Global Constraints

- Preserve exact `test_000004.png` caption, class counts 45598/7382/12556, changed count 19938, and raw mask.
- Keep the checkpoint and dataset external; do not vendor either.
- Do not touch SatQuery API, routing, registry, composer, checker, frontend, Tool 1, or Tool 3.
- Do not add LLM, agent, training, full-evaluation, GeoTIFF, or main-environment dependencies.
- Keep physical area/coordinates null without validated projected-metric metadata and confidence score null.

---

### Task 1: Vendor and freeze the MCI runtime

**Files:**
- Create: `experiments/tool2_mci/vendor/change_agent_mci/{__init__.py,model_encoder_att.py,model_decoder.py,segformer.py,vocab.json,LICENSE.txt,ATTRIBUTION.md}`
- Modify: `experiments/tool2_mci/mci_inference.py`
- Modify: `experiments/tool2_mci/run_smoke.py`
- Test: `tests/test_tool2_mci_vendor.py`

**Interfaces:**
- Consumes: external checkpoint path and 256x256 RGB image paths.
- Produces: `MCIInference(checkpoint_path, vocab_path=None, device=None)` and `MCIPrediction` without any `Change-Agent-main` import.

- [x] Write a failing test that asserts the default vocabulary has 468 contiguous IDs, vendored imports resolve, runtime source contains no `Change-Agent-main`, and the expensive regression test expects the frozen caption/counts/mask.
- [x] Run `\.venv-mci\Scripts\python.exe -m unittest tests.test_tool2_mci_vendor` and verify failure because the vendor package is absent.
- [x] Add the minimum three architecture files, vocabulary, license, attribution, and remove preliminary MiT/mmcv/mmseg loading that is superseded by the strict full encoder checkpoint.
- [x] Change `MCIInference` to relative vendor imports and a default vendored vocabulary; retain strict encoder/decoder and original `strict=False` attentive loading.
- [x] Run the vendor unit test and focused Phase 1 helper tests.
- [x] Run checkpoint regression and assert the caption, counts, and mask equal the frozen baseline.

### Task 2: Statistics and connected components

**Files:**
- Create: `experiments/tool2_mci/analysis.py`
- Test: `tests/test_tool2_change_analysis.py`

**Interfaces:**
- Consumes: `numpy.ndarray` semantic mask and optional validated metadata.
- Produces: `compute_change_statistics(mask, valid_mask=None)`, `extract_change_components(mask, min_pixels=6, connectivity=8)`, and `physical_area_from_metadata(changed_pixels, metadata)`.

- [x] Write failing synthetic tests for empty, roads-only, buildings-only, mixed and invalid masks; exact fractions; raw/filtered 8-connected components; bounding boxes/centroids; and unavailable physical area.
- [x] Run the focused test and verify missing-function failures.
- [x] Implement validated class/changed statistics with both required sum invariants.
- [x] Implement deterministic 8-connected flood-fill components with 0-based centroids and exclusive-max pixel bounding boxes.
- [x] Implement physical-area calculation only for metadata marked validated, projected, and metric; otherwise return null values plus the required warning.
- [x] Run focused tests and verify all pass.

### Task 3: Evidence artifacts and stable result

**Files:**
- Create: `experiments/tool2_mci/artifacts.py`
- Create: `experiments/tool2_mci/result.py`
- Create: `experiments/tool2_mci/change_analysis_tool.py`
- Test: `tests/test_tool2_change_analysis.py`

**Interfaces:**
- Consumes: a reusable runtime exposing `predict(before, after) -> MCIPrediction`.
- Produces: `ChangeAnalysisTool.analyze(before_path, after_path, question=None, geo_metadata=None, output_dir=None, job_id=None) -> Tool2Result` and `Tool2Result.to_dict()`.

- [x] Add failing tests using a deterministic fake runtime for artifact dimensions/palette, unique directories, question provenance, null confidence, geospatial warning, and JSON serialization.
- [x] Run tests and verify behavior failures.
- [x] Implement artifact writing for before/after, raw/RGB/binary masks, overlay, components JSON, and result JSON.
- [x] Implement frozen dataclasses for caption, confidence, timing, and the top-level result; serialize paths as absolute strings.
- [x] Implement `ChangeAnalysisTool` orchestration, model/checkpoint provenance, warnings, and timing without reloading the injected runtime.
- [x] Run focused tests and verify all pass.

### Task 4: Two real checkpoint-backed analyses

**Files:**
- Create: `experiments/tool2_mci/run_analysis.py`
- Test: `tests/test_tool2_mci_checkpoint.py`

**Interfaces:**
- Consumes: external checkpoint, test A/B roots, and deterministic sample filenames.
- Produces: separate Tool 2 output directories and complete `result.json` files for `test_000004.png` and `test_000005.png` from one runtime instance.

- [x] Write the opt-in checkpoint test that compares `test_000004` with the frozen caption, counts, and raw mask.
- [x] Run with `RUN_MCI_CHECKPOINT_TEST=1` and verify it fails until the runner/adapter is complete.
- [x] Implement a CLI that creates one `MCIInference`, one `ChangeAnalysisTool`, analyzes the frozen sample, then selects the next lexicographically valid matching pair without inspecting labels.
- [x] Run all synthetic/focused tests.
- [x] Run the checkpoint regression and two-sample CLI on CUDA.
- [x] Verify every artifact exists/aligned, both JSON files deserialize, and `test_000004` exactly matches Phase 1.
