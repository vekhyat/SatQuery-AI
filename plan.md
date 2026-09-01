# SatQuery AI — SIH26167 Project Map

## 1. What we are building

SatQuery AI is a web application that lets a non-GIS user upload one satellite image or a compatible image pair, ask a natural-language question, and receive:

- a direct textual answer;
- visual evidence on the image or map;
- calibrated confidence and warnings;
- a downloadable analysis report; and
- an auditable execution summary showing the chosen task, tools/models, and permitted parameters.

This is not one general-purpose VLM. It is an agentic controller over remote-sensing specialist tools.

## 2. Mandatory acceptance checklist

The final system must demonstrate all of the following:

| Requirement | Minimum proof in our demo |
|---|---|
| Remote-sensing adaptation | At least one trainable vision/VLM component adapted on BigEarthNet or another open remote-sensing dataset, with the training recipe and checkpoint supplied |
| Single-image VQA | Ask questions about one optical/multispectral or SAR image and evaluate on VRSBench/RSVQA |
| One additional single-image task | Implement captioning first; grounding is a high-value follow-up |
| Bi-temporal analysis | Answer what changed between spatially aligned before/after images and identify where it happened |
| Optical–SAR analysis | Jointly use co-registered optical and SAR inputs; show that both modalities contribute |
| Agentic orchestration | Automatically validate input, classify intent, select tools, run them, fuse outputs, and expose the execution trace |
| Supported inputs | GeoTIFF/TIFF for real geospatial data; PNG/JPEG only for prescribed benchmark samples |
| Evidence and reporting | Overlays/maps, confidence, warnings, execution summary, and downloadable report |
| Deliverables | Interactive app, source code, model checkpoints/configs, tests, reproducible demo |

We should treat paired optical–SAR and bi-temporal reasoning as the centre of the product. A single-image chatbot alone does not satisfy the statement.

## 3. Proposed user flow

1. User chooses `Single image`, `Optical + SAR`, or `Before + After`.
2. User uploads the image(s) and optionally corrects detected sensor/date metadata.
3. The validator reads the raster metadata and checks modality, format, CRS, transform, bounds, resolution, band count, no-data areas, and pair compatibility.
4. The user asks a natural-language question.
5. The router returns a strict task plan such as `change_vqa -> change_map -> evidence_summary`.
6. The tool registry validates that plan and allows only safe, predefined parameters.
7. Specialist model(s) execute and return structured facts, spatial evidence, uncertainty, and provenance.
8. The response composer turns only those facts into a concise answer, without inventing unsupported observations.
9. The UI shows the answer, overlay, confidence, warnings, metadata, and execution trace.
10. The user downloads a PDF/JSON/GeoJSON result package.

## 4. System architecture

```text
React/MapLibre web client
        |
        v
FastAPI upload + query API
        |
        +--> Raster validator and preprocessor (GDAL/rasterio)
        |      - metadata and modality checks
        |      - band selection / percentile stretch
        |      - alignment, tiling, and coordinate mapping
        |
        +--> Query router (strict JSON task schema)
        |      - intent + requested objects/areas/change type
        |      - input/tool compatibility checks
        |
        +--> Versioned specialist-tool registry
        |      - single-image VQA/captioning
        |      - optional text-guided grounding
        |      - bi-temporal change VQA/map
        |      - optical–SAR fusion
        |
        +--> Evidence and confidence fusion
        |      - structured facts only
        |      - calibrated confidence / abstention
        |      - pixel-to-map-coordinate conversion
        |
        +--> Report and audit generator
               - response, overlays, metrics, metadata, trace

Model service / GPU worker
Object storage for uploads and outputs
Experiment tracking + model registry
```

The controller must expose an observable trace, not hidden chain-of-thought. Example:

```json
{
  "task": "bitemporal_change_vqa",
  "inputs": ["before.tif", "after.tif"],
  "tools": ["raster_compatibility_v1", "change_encoder_v2", "change_vqa_v1"],
  "parameters": {"tile_size": 512, "change_threshold": 0.63},
  "warnings": [],
  "artifacts": ["change_mask.tif", "change_overlay.png"]
}
```

## 5. Model plan

### A. Shared remote-sensing adaptation

Use paired BigEarthNet Sentinel-1/Sentinel-2 patches to learn remote-sensing features rather than relying only on natural-image features.

Recommended first experiment:

- modality-specific input stems for SAR and multispectral bands;
- shared or aligned vision embedding space;
- multi-label land-cover objective plus optical–SAR contrastive alignment;
- parameter-efficient fine-tuning where possible;
- saved training config, split, seed, metrics, and checkpoint.

BigEarthNet labels can be converted to short, deterministic text descriptions for image–text alignment, but generated text must not contaminate benchmark test data.

### B. Single-image specialist

Start with VQA plus captioning because this satisfies the mandatory baseline with the lowest integration risk.

- Baseline: an open VLM with a remote-sensing visual adapter/LoRA.
- Training/evaluation: VRSBench and RSVQA prescribed splits.
- Outputs: answer/caption, answer confidence, and evidence heatmap or referenced region when available.
- Stretch goal: text-guided grounding trained/evaluated on VRSBench references.

### C. Bi-temporal change specialist

Do not ask a single-image model to concatenate two pictures and guess.

- Siamese or dual-temporal image encoder with shared weights;
- explicit feature-difference/cross-attention tokens;
- CDVQA-trained answer head;
- optional segmentation head for a spatial change mask;
- structured output: change type, direction, affected class, area/location, confidence, and mask/heatmap.

### D. Optical–SAR fusion specialist

- separate optical and SAR stems/encoders;
- gated or cross-attention feature fusion;
- land-cover/object presence head first, pixel-level map head next;
- modality-ablation evaluation: optical only vs SAR only vs fused;
- structured output describing what each sensor contributed.

The ablation is essential evidence that the pair is actually used rather than one image being ignored.

## 6. Data and evaluation plan

| Capability | Primary data | Initial metrics |
|---|---|---|
| Domain adaptation / optical–SAR | BigEarthNet S1/S2 | macro/micro F1, mean average precision, retrieval/alignment score, fused-vs-single ablation |
| VQA | VRSBench, RSVQA | exact/soft accuracy plus category-wise accuracy |
| Captioning | VRSBench | BLEU-4, METEOR, ROUGE-L, CIDEr and semantic/human review |
| Grounding (stretch) | VRSBench | IoU and Acc@0.5/Acc@0.7 |
| Change VQA | CDVQA | overall and per-question-type accuracy |
| Change map | data with masks | IoU/F1, precision, recall |
| Router | our labelled query suite | intent accuracy, invalid-plan rate, tool-selection accuracy |
| End-to-end | held-out scenarios | factual correctness, evidence consistency, abstention quality, latency |

Rules:

- freeze official test subsets; never train or tune on them;
- version every preprocessing pipeline and split;
- add sensor/geography/domain-shift slices;
- measure confidence calibration, not only raw accuracy;
- include negative and incompatible-input tests;
- keep an evaluation harness from the first model baseline onward.

The problem statement's evaluation-weight table is currently absent from the supplied text. We must update priorities when SIH/ISRO publishes the authoritative table.

## 7. Geospatial engineering requirements

- Inspect CRS, affine transform, resolution, bounds, dimensions, bands, data type, no-data mask, and metadata tags.
- Detect or request optical/SAR modality and acquisition date; never silently guess when ambiguous.
- Reject incompatible pairs or offer a logged reprojection/resampling step.
- Keep original rasters unchanged; derived previews and aligned copies are separate artifacts.
- Use sensor-appropriate normalization. SAR needs different preprocessing from RGB imagery.
- Support large rasters through tiling with overlap and deterministic stitching.
- Convert model pixel coordinates/masks back to original raster and geographic coordinates.
- Preserve georeferencing in downloadable GeoTIFF/GeoJSON outputs.

## 8. Narrow MVP and progression

### Milestone 0 — Reproducible data spike

- confirm exact licenses, downloads, official splits, storage, and GPU budget;
- load one sample from each dataset;
- render optical, multispectral, SAR, and temporal pairs correctly;
- define schemas for input metadata, task plan, model result, evidence, and audit trace.

Exit condition: one command validates and visualizes representative inputs from every required modality.

### Milestone 1 — End-to-end vertical slice

- basic web upload/query interface;
- GeoTIFF validator and preview;
- rule-based query router with strict tool schemas;
- stub/mock specialists returning structured outputs;
- overlay, confidence, trace, and downloadable JSON report.

Exit condition: every required workflow runs end-to-end even before strong models are plugged in.

### Milestone 2 — Mandatory single-image baseline

- VRSBench/RSVQA evaluation harness;
- adapted VQA model;
- captioning model/task;
- benchmark results and qualitative failure gallery.

Exit condition: reproducible checkpoint beats its unadapted baseline and is callable through the app.

### Milestone 3 — Bi-temporal change

- CDVQA baseline and dual-temporal model;
- change answer plus location evidence;
- optional change-mask head;
- before/after slider and overlay in UI.

Exit condition: held-out change questions are answered with spatially consistent evidence.

### Milestone 4 — Optical–SAR fusion

- paired preprocessing and compatibility checks;
- fusion model and land-cover outputs;
- optical/SAR/fused ablation;
- UI layer toggle and contribution summary.

Exit condition: fused performance is measured against both single modalities and the app explains the source evidence.

### Milestone 5 — Hardening and jury demo

- calibrated confidence and honest abstention;
- adversarial/invalid input tests;
- latency and GPU-memory profiling;
- report generation and complete execution traces;
- scripted offline demo with local checkpoints and cached samples;
- installation, training, evaluation, and model-card documentation.

Exit condition: the full demo works without internet and can be reproduced on a clean machine.

## 9. Demo story

Use three short cases rather than one long free-form chat:

1. **Single image:** ask about visible land cover and major objects; show caption/VQA, evidence, and trace.
2. **Before/after:** ask whether built-up or water-covered area changed; show slider, change overlay, area statistics, answer, and uncertainty.
3. **Optical + SAR:** use a cloudy/flood or built-up scene where SAR adds information; toggle optical, SAR, and fused results, then show the ablation/confidence difference.

Finish by deliberately uploading an incompatible pair so the validator refuses it and explains why. That proves the system is operationally trustworthy, not only visually impressive.

## 10. Suggested six-person ownership

| Owner | Primary responsibility | Integration obligation |
|---|---|---|
| 1. ML/data lead | dataset registry, splits, shared adaptation, experiment tracking | publishes stable encoder/checkpoint interfaces |
| 2. VLM lead | single-image VQA, captioning, optional grounding | conforms to common result/evidence schema |
| 3. Change lead | CDVQA, temporal encoder, mask/heatmap | supplies spatially referenced change outputs |
| 4. Fusion lead | optical–SAR preprocessing/model/ablation | documents modality contribution and limitations |
| 5. Platform lead | FastAPI, controller, tool registry, jobs, storage, reports | owns end-to-end contracts and reproducibility |
| 6. Product/UI lead | React/MapLibre UI, raster/overlay interaction, UX, pitch demo | integrates every real workflow early |

Everyone owns tests and documentation for their component. At least one shared integration session should happen every week; model branches must not wait until the final week to meet the app.

## 11. Repository shape

```text
apps/
  web/                 # React UI and map/overlay viewers
  api/                 # FastAPI endpoints and job control
satquery/
  agent/               # intent schema, planner, registry, executor
  geospatial/          # validation, preprocessing, tiling, coordinate transforms
  models/
    single_image/
    change/
    optical_sar/
  evidence/            # confidence, overlays, provenance, report data
training/
  configs/
  datasets/
  experiments/
evaluation/
tests/
demo/
docs/
```

Large datasets, checkpoints, secrets, and generated rasters must stay out of Git. Store only manifests, download/preparation scripts, small permitted samples, configs, and checksums.

## 12. Major risks and mitigations

| Risk | Mitigation |
|---|---|
| Scope is too broad | Build the vertical slice first; captioning before grounding; one strong paired workflow before extras |
| GPU/storage limits | Data subset spike, parameter-efficient fine-tuning, mixed precision, cached features, explicit budget before model choice |
| VLM hallucination | structured specialist outputs, evidence requirement, confidence calibration, abstention, no unsupported prose |
| SAR is treated as RGB | modality-specific preprocessing/encoders and separate tests |
| Pair is not truly aligned | strict metadata/grid checks and logged reprojection; reject uncertain pairing |
| Model ignores one modality | optical-only/SAR-only/fused ablation plus attention/contribution evidence |
| Benchmark leakage | immutable split manifests and dataset checksums |
| Large GeoTIFF crashes app | size limits, tiled jobs, progress, cancellation, controlled temporary storage |
| Demo depends on internet | local models, fixed test samples, cached outputs only as fallback and visibly labelled |
| Missing official evaluation weights | track SIH clarification and keep modular evaluation so priorities can change quickly |

## 13. Decisions to make immediately

Before implementation, the team must lock:

1. available GPU model/VRAM, hours, storage, and whether training can use a cloud notebook/server;
2. whether the first additional single-image task is captioning (recommended) or grounding;
3. exact open-source base checkpoints and licenses;
4. approved dataset versions and immutable train/validation/test manifests;
5. the first three demo scenes and their expected, verifiable answers;
6. frontend target: production React/MapLibre from the start, or Gradio only for an early ML spike;
7. who owns each of the six streams above.

## 14. First working sprint

- Download metadata and tiny samples—not full datasets yet.
- Build the dataset/license/metric matrix.
- Write shared Pydantic schemas for inputs, task plans, model outputs, evidence, and trace.
- Implement GeoTIFF inspection and pair-compatibility checks with tests.
- Implement the strict rule-based router for the representative queries.
- Create the UI shell for single, temporal, and optical–SAR modes.
- Run unadapted baseline inference on one VRSBench, one CDVQA, and one BigEarthNet pair.
- Record GPU memory, runtime, expected training cost, failure modes, and next experiment.

The first sprint output should be an integrated skeleton plus evidence that the chosen model/data path is computationally feasible—not a polished landing page.
