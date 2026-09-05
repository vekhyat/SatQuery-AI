# SatQuery AI

<!-- impeccable:product-schema 1 -->

## Platform

web

## Product Purpose

SIH26167: an interactive vision-language assistant for multimodal remote-sensing image analysis through text queries. Repository truth: upload satellite files, validate geospatial metadata, route a question to one specialist tool, and present an answer with spatial evidence and a visible receipt.

## Users

The first prototype is for the SIH team demonstration. A satellite-image analyst is the working audience hypothesis; specific professional roles remain unconfirmed.

## Capabilities and Constraints

The existing Python API exposes health, upload, and query endpoints. Its checker verifies GeoTIFF metadata and exact-grid compatibility; its deterministic router selects single_image, change, optical_sar, or reject. Specialist analysis tools are currently stubs. Visual concepts must label satellite imagery, overlays, and proposed analysis findings as illustrative, and must not imply live analysis or validated accuracy.

## Operating Context

The planned workflow is upload one or two scenes, ask a question, inspect map evidence, read warnings and the execution receipt, and download a report. Before/after comparison is an important demonstration workflow. The API result contract is authoritative for later integration.

## Brand Commitments

SatQuery AI. On 5 September 2026 the user approved direction C, Query Notebook, in design-mockups/C-query-notebook.png and requested implementation with libraries.dev UI elements and project-driven UX. The user requests Grok subagents. React and TypeScript are selected to support the requested React libraries; Vite hosts the local prototype alongside the existing Python API.

## Evidence on Hand

README.md, handbook.html, apps/api/main.py, and satquery/contracts.py. No satellite scenes are supplied in this checkout. The handbook is team documentation, not an established product interface.

## Product Principles

- Keep visual evidence close to the question and answer.
- Make routing and limitations inspectable.
- Distinguish demonstration material from computed results.
- Keep the first demonstration understandable to a beginner team.
