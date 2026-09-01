# SIH26167 · SatQuery AI

ISRO problem statement: **SatQuery AI** — an interactive vision-language assistant for multimodal remote-sensing image analysis through text queries.

**Repo:** https://github.com/vekhyat/SIH26167

## Start here

Open [`handbook.html`](handbook.html) in a browser. That is the team briefing: architecture, teaching notes (including LoRA), work order, checklists, PPT/video plan.

## Docs in this repo

| File | What it is |
|---|---|
| `handbook.html` | Full handbook (use this) |
| `ARCHITECTURE.md` | System map |
| `TEAM_LEADER_BRIEF.md` | Leader brief |
| `TEAM_SPLIT.md` | Six-person split |
| `plan.md` | Longer technical plan |

## What we are building

A website: upload satellite file(s), ask a question, a **code router** picks one of three tools (single image, before/after change, optical+SAR), and facts are drawn on a map with a visible receipt.

Not three LLMs. A VLM/LoRA upgrade, if any, sits inside the single-image tool after the 12 Sep internal demo.
