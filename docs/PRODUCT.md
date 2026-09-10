# SatQuery AI

<!-- impeccable:product-schema 1 -->

## Platform

web

## Product Purpose

SIH26167: an interactive vision-language assistant for multimodal remote-sensing image analysis through text queries. Repository truth: upload satellite files, validate geospatial metadata, route a question to one specialist tool, and present an answer with spatial evidence and a visible receipt.

## Users

The first prototype is for the SIH team demonstration. A satellite-image analyst is the working audience hypothesis; specific professional roles remain unconfirmed.

## Capabilities and Constraints

The existing Python API exposes health, upload, and query endpoints. Its checker verifies GeoTIFF metadata and exact-grid compatibility; its deterministic router selects single_image, change, optical_sar, or reject. Tool 2 runs pretrained Change-Agent MCI in a separate local worker for exact-grid 256×256 uint8 RGB optical pairs with different dates. It returns a change caption, semantic masks, and statistics. Optical–SAR Tool 3 computes threshold candidate maps; only single-image analysis remains a stub. Tool 2 is not question-conditioned VQA. Label prepared demos as illustrative, distinguish computed results from demos, and never imply calibrated accuracy.

## Operating Context

The implemented notebook workflow is upload one or two scenes, ask a question, inspect map evidence, read warnings and the execution receipt, and download result JSON or an execution receipt. Tool 2 also exposes mask/overlay PNGs and components JSON; Tool 3 exposes its own reports and artifacts. Before/after comparison is an important demonstration workflow. The API result contract is authoritative for the integrated notebook.

## Brand Commitments

SatQuery AI. The shipped interface is the Query Notebook in `apps/web`. React and TypeScript host the notebook; Vite builds the frontend; the combined Python server serves it with the API. The model worker runs separately. Libraries.dev Border Beam and Thinking Orbs provide focus and waiting feedback.

## Evidence on Hand

README.md, docs/TOOL2.md, docs/TOOL2_IMPLEMENTATION_HANDOFF.md, docs/TOOL3_HANDOFF.md, apps/api/main.py, and satquery/contracts.py. Tool 3 has a synthetic Pack C generator; the notebook has illustrative scenery. The Tool 2 checkpoint and LEVIR-MCI dataset are external, Git-ignored prerequisites. The handbook is team documentation, not an established product interface.

## Product Principles

- Keep visual evidence close to the question and answer.
- Make routing and limitations inspectable.
- Distinguish demonstration material from computed results.
- Keep the first demonstration understandable to a beginner team.
