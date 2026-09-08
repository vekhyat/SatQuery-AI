# SatQuery AI

<!-- impeccable:product-schema 1 -->

## Platform

web

## Product Purpose

SIH26167: an interactive vision-language assistant for multimodal remote-sensing image analysis through text queries. Repository truth: upload satellite files, validate geospatial metadata, route a question to one specialist tool, and present an answer with spatial evidence and a visible receipt.

## Users

The first prototype is for the SIH team demonstration. A satellite-image analyst is the working audience hypothesis; specific professional roles remain unconfirmed.

## Capabilities and Constraints

The existing Python API exposes health, upload, and query endpoints. Its checker verifies GeoTIFF metadata and exact-grid compatibility; its deterministic router selects single_image, change, optical_sar, or reject. Optical–SAR Tool 3 computes threshold candidate maps; single-image and change tools remain stubs. Visual concepts must label satellite imagery, overlays, and proposed analysis findings as illustrative, and must not imply live analysis or validated accuracy.

## Operating Context

The planned workflow is upload one or two scenes, ask a question, inspect map evidence, read warnings and the execution receipt, and download a report. Before/after comparison is an important demonstration workflow. The API result contract is authoritative for later integration.

## Brand Commitments

SatQuery AI. The shipped interface is the Query Notebook in `apps/web`. React and TypeScript host the notebook; Vite serves it locally alongside the Python API. Libraries.dev Border Beam and Thinking Orbs provide focus and waiting feedback.

## Evidence on Hand

README.md, docs/handbook.html, apps/api/main.py, and satquery/contracts.py. No satellite scenes are supplied in this checkout. The handbook is team documentation, not an established product interface.

## Product Principles

- Keep visual evidence close to the question and answer.
- Make routing and limitations inspectable.
- Distinguish demonstration material from computed results.
- Keep the first demonstration understandable to a beginner team.
