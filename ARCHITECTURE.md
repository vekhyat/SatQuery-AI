# SatQuery AI — Architecture (plain language)

Read this as a map of a **building**, not a map of models.

You are building a **desk** that takes satellite files + a question, sends the job to the right **room**, and puts the answer on a map.

Almost every box below is **code**. A few rooms contain a **small specialist tool**. None of the boxes is “an LLM that runs the company.”

---

## 1. One picture of the whole system

```
┌─────────────────────────────────────────────────────────────┐
│                         WEBSITE                              │
│  [Single image] [Before/After] [Optical + SAR]               │
│  Upload files · type question · see map · download report    │
└──────────────────────────┬──────────────────────────────────┘
                           │  files + question
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    API  (the front door)                     │
│              receives upload, returns job status             │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              CHECKER  (code, not a model)                    │
│  Can we read this file? GeoTIFF? How many images?            │
│  Optical or radar? Same place? Dates? Bands?                 │
│  If junk → STOP and explain. Never guess.                    │
└──────────────────────────┬──────────────────────────────────┘
                           │  clean files + metadata
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              ROUTER  (code, not a model)                     │
│  Read the question + how many files + what kind              │
│  Pick ONE plan from a fixed list:                            │
│    single_vqa  |  caption  |  change  |  optical_sar         │
│  Write a receipt (JSON plan). That is the "agent".           │
└──────────────────────────┬──────────────────────────────────┘
                           │  plan: which tool, allowed settings
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              TOOL REGISTRY  (a menu, not a brain)            │
│  Only these tools exist. Router cannot invent a new one.     │
│                                                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐                   │
│   │ SINGLE   │  │ CHANGE   │  │ OPT+SAR  │                   │
│   │ IMAGE    │  │ (before/ │  │ FUSION   │                   │
│   │ TOOL     │  │  after)  │  │ TOOL     │                   │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘                   │
│        │             │             │                         │
└────────┼─────────────┼─────────────┼─────────────────────────┘
         │             │             │
         ▼             ▼             ▼
   facts + mask   facts + mask   facts + mask
   (JSON)         (JSON)         (JSON)
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│           COMPOSER  (code, not a model)                      │
│  May ONLY use the JSON facts. Cannot invent objects.         │
│  Builds: English sentence + overlay + confidence + receipt   │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│           REPORT  (code)                                     │
│  PDF / JSON / GeoJSON  +  show everything on the website     │
└─────────────────────────────────────────────────────────────┘
```

If you remember only this: **Website → Checker → Router → One tool → Composer → Screen.**

---

## 2. Same idea as a hospital desk

| In a hospital | In SatQuery AI |
|---|---|
| Reception checks your ID and forms | **Checker** reads the GeoTIFF |
| Reception sends you to the right ward | **Router** picks the tool |
| The menu of wards is fixed | **Tool registry** (only 3 rooms) |
| A specialist does the test | **One tool** runs |
| Results printed on a report | **Composer + report** |
| You do not train a super-doctor to do every ward | You do not train one VLM to do everything |

The receptionist is **not** a doctor. The receptionist is **code**.

---

## 3. What each box is, in / out

### A. Website
**What:** React (or similar) page with a map.
**In:** clicks, files, question text.
**Out:** shows preview, answer, red overlay, confidence, tool receipt, download button.
**Is it a model?** No. It is a screen.

Three modes on the screen. That is the whole product the user sees.

### B. API
**What:** FastAPI (or similar). One upload endpoint, one “ask” endpoint.
**In:** files + question.
**Out:** job id, then the final JSON result.
**Is it a model?** No.

### C. Checker
**What:** Python + rasterio/GDAL. Reads satellite file headers.
**Checks:**
- format (GeoTIFF vs random PNG)
- how many images
- optical vs SAR (from metadata / band count — if unsure, ask the user)
- size, map projection, whether two images cover the same place
- dates, if present
**Out:** either “ok + metadata” or “rejected + reason.”
**Is it a model?** No. This box is how you prove the system is trustworthy.

### D. Router (this is the “agent”)
**What:** if-then rules that write a JSON plan.
**In:** metadata + question text.
**Rules (enough for SIH):**

```
if files invalid                  → reject
if 1 image                        → single_image tool
if 2 images, different dates      → change tool
if 1 optical + 1 SAR, same place  → optical_sar tool
if question doesn't match files   → reject and explain
```

**Out:** a plan like:

```json
{
  "task": "bitemporal_change",
  "tools": ["checker_v1", "change_tool_v1"],
  "parameters": { "tile_size": 512, "threshold": 0.63 },
  "inputs": ["before.tif", "after.tif"]
}
```

**Is it a model?** No. You can add a tiny text classifier later if questions are messy. You do **not** train an LLM to be the router.

### E. Tool registry
**What:** a dictionary in code: name → function.
**Why it exists:** the router may only call names on this list, with only allowed settings. No free-form “run anything.”

### F. The three tools (the only place “AI” can live)

Each tool **must** return the same shape of result, so the composer never cares which tool ran:

```json
{
  "facts": { "...depends on the tool..." },
  "answer_key": "increased",
  "mask": "<optional pixels to paint>",
  "confidence": 0.74,
  "warnings": [],
  "provenance": { "tool": "change_tool_v1", "version": "0.1" }
}
```

#### Tool 1 — Single image
**Job:** “What’s in this picture?” / “Describe it.”
**Simplest version:** land-cover classifier (forest / water / urban / crop…). Caption is a template: “This scene contains: water, forest.” VQA is: “Is there water?” → yes if water score is high.
**Later version:** same tool, better weights, trained on BigEarthNet. Still returns JSON, not a chat.
**Is it an LLM?** No.

#### Tool 2 — Change (before / after)
**Job:** “What changed, and where?”
**Simplest version:** align two images, subtract, threshold, paint red, count area, say increased / decreased / unchanged.
**Later version:** a dual-image change network. Same JSON out.
**Is it an LLM?** No. Do **not** show two screenshots to a chatbot.

#### Tool 3 — Optical + SAR
**Job:** use photo **and** radar together.
**Simplest version:** run land-cover on optical, run land-cover on SAR, combine (e.g. water from SAR if optical is cloudy). UI toggle: optical / SAR / fused.
**Later version:** a two-stem fusion model. Same JSON out.
**Proof it used both:** show fused ≠ optical-only.

### G. Composer
**What:** code that turns JSON facts into the sentence on screen.
**Rule:** if a fact is not in the JSON, it must not appear in the sentence.
**Is it a model?** No. Optional later: a small rewriter that is **only** allowed to polish the sentence, never add objects.

### H. Report
**What:** pack answer, overlay, metadata, receipt into JSON/PDF/GeoJSON.
**Is it a model?** No.

---

## 4. Three paths through the same building

The architecture does not change. Only the door and the room change.

### Path A — one image
```
Upload 1 file → Checker OK → Router: single_image
  → Tool 1 returns labels + optional heatmap
  → Composer: "Land cover: water, forest, urban. Confidence 0.81."
  → Map shows preview + heatmap
  → Receipt: single_image_v1
```

### Path B — before / after
```
Upload 2 files → Checker: same place? different dates? else REJECT
  → Router: change
  → Tool 2 returns change type + red mask + area
  → Composer: "Built-up increased (~12 ha). Confidence 0.74."
  → Map: slider + red overlay
  → Receipt: change_tool_v1, threshold 0.63
```

### Path C — optical + radar
```
Upload 2 files → Checker: one optical, one SAR, same place? else REJECT
  → Router: optical_sar
  → Tool 3 returns fused labels + two extra maps (optical-only, SAR-only)
  → Composer: "Water and built-up from both sensors. SAR added water under cloud."
  → Map: toggle Optical / SAR / Fused
  → Receipt: fusion_tool_v1
```

### Path D — junk (this is part of the architecture)
```
Upload two files of different cities
  → Checker: bounds do not match → REJECT
  → Screen: "These images are not the same place. I will not guess."
  → No tool runs. Receipt shows the refusal.
```

---

## 5. What data looks like as it moves (one change example)

**User types:** “Has the built-up area increased, decreased, or remained unchanged?”

**Checker out:**

```json
{
  "ok": true,
  "n_images": 2,
  "modality": ["optical", "optical"],
  "aligned": true,
  "dates": ["2018-03-12", "2024-02-04"]
}
```

**Router out:**

```json
{
  "task": "bitemporal_change",
  "tools": ["change_tool_v1"],
  "parameters": { "threshold": 0.63 }
}
```

**Tool out:**

```json
{
  "answer_key": "increased",
  "facts": { "class": "built-up", "area_ha": 12.4 },
  "mask": "change_mask.tif",
  "confidence": 0.74
}
```

**Composer out (what the human reads):**

> Built-up area increased between 2018 and 2024 (~12.4 ha). Confidence 0.74.

**Screen also shows:** before/after slider, red overlay, the JSON receipt above.

Nothing in this pipeline “wrote an essay about the image.”

---

## 6. What is code vs what is a model

```
CODE (you write this; this IS the product)
  website, API, checker, router, registry, composer, report, overlays

SMALL TOOL (optional AI inside a room)
  single-image land-cover
  change comparator
  optical+SAR combiner

NOT IN THIS ARCHITECTURE
  an LLM that routes
  an LLM that writes the answer from scratch
  one VLM that does all three modes
  ChatGPT API
```

ISRO’s “agentic” word = **router + registry + receipt**.  
ISRO’s “adapted to remote sensing” word = **at least one of the three tools learned from satellite data** (BigEarthNet), not from cat photos.

Those are two different boxes. Do not merge them into “we train a VLM.”

---

## 7. What you build by 12 Sep vs later

Same architecture. Only the inside of the three rooms gets better.

| Box | Internal hackathon (now) | If nominated (later) |
|---|---|---|
| Website | Real, 3 modes, demo-proof | Same, prettier |
| Checker | Real enough to reject junk | Stricter GeoTIFF / CRS |
| Router | If-then + JSON receipt | Same (maybe slightly smarter rules) |
| Single-image tool | Classifier or even a stub on known demo images | Weights trained on BigEarthNet |
| Change tool | Difference + overlay on demo pair | Stronger pair model, CDVQA |
| Optical+SAR tool | Two maps + toggle on demo pair | Fusion model + ablation numbers |
| Composer / report | Template sentence + JSON download | PDF + GeoJSON |

The **shape of the system does not change**. You never replace the desk with a chatbot.

---

## 8. Where VLM fine-tuning fits (and where it does not)

It does **not** replace the architecture. It is an optional upgrade **inside Tool 1** (single-image room), after the desk already works.

```
Website          ← never a VLM
Checker          ← never a VLM
Router           ← never a VLM
Composer         ← never a VLM
Report           ← never a VLM

Tool 1 Single image
   TODAY:  classifier / stub / template caption
   LATER:  you MAY drop a fine-tuned VLM in HERE
           image + question → JSON facts
           same door, same JSON out

Tool 2 Change    ← not a VLM (pair comparison)
Tool 3 Opt+SAR   ← not a VLM (two sensors). A VLM could help later; not required
```

**Why ISRO mentioned VLMs at all**  
A generic VLM (ChatGPT-with-eyes) fails on satellite/radar data. So **if** you use a VLM for single-image Q&A, you must adapt it on BigEarthNet.txt (or similar). That sentence is a warning, not an instruction to make the whole product a VLM.

**What “fine-tune a VLM” actually means in this project**
- Take a **small** open VLM (about 1B–3B, LoRA, not full training).
- Train it on satellite image–text (BigEarthNet.txt): captions + VQA.
- Plug it into Tool 1 **only**.
- It must still return JSON facts, not a free chat.

**You can skip the VLM entirely** and still satisfy “adapted to remote sensing” by training a **land-cover classifier** on BigEarthNet and putting *that* in Tool 1. Same checkbox, smaller job.

**When:** not before 12 Sep. After nomination, M4 owns this upgrade. M1’s router and M2’s UI do not change.

---

## 9. One sentence for the architecture

> SatQuery AI is a website whose backend checks satellite files, routes the question to one of three specialist tools, and prints only that tool’s facts onto a map with a visible receipt.

If you can sketch the picture in section 1 from memory, you understand the architecture.
