# SIH26167 — Team Leader Brief

Read this once slowly. If you can explain this to a faculty member in 5 minutes, you understand the problem.

**PS:** SIH26167
**Title:** SatQuery AI — An Interactive Vision-Language Assistant for Multimodal Remote Sensing Image Analysis through Text Queries
**Who asked for it:** ISRO (Department of Space)
**Category:** Software · Theme: Space Technology
**Your job until 12 Sep:** understand it, pitch it, and show a working prototype. Full models come later.

---

## 0. You are not training a VLM

If someone asks “so you guys are fine-tuning a VLM?” the answer is **no**.

You are building **software**: a website + a manager that checks satellite files, picks the right specialist tool, and returns an answer drawn on the map.

A model is one **tool inside** that software, the way a calculator is a tool inside Excel. Excel is not “we trained a calculator.”

| Wrong picture | Right picture |
|---|---|
| We train a satellite ChatGPT and put a chat box on it | We build SatQuery AI. One of its rooms can answer questions about a single image. That room must know satellite pictures, not cat pictures. |
| The project = GPU + LLaVA + dataset | The project = upload, checks, routing, overlays, reports, and three tools |
| Success = a trained checkpoint | Success = a user asks a question and gets evidence on the map |

ISRO even says a **single generic VLM is the thing they do not want**, even if you fine-tune it.

You can do single-image Q&A **without** a ChatGPT-style VLM at all: a satellite land-cover classifier + a question router (“is there water?” → check the water label). That is still “vision + language.” It is not “we trained InternVL.”

---

## 1. The problem in one paragraph

ISRO has huge amounts of satellite pictures of Earth. Those pictures are used for floods, farms, cities, forests, water, and disasters.

Today, each AI tool does **one** job: classify land, find objects, detect change, and so on. To use them you need GIS knowledge: which sensor, which model, which settings. A district officer, planner, or disaster team cannot just upload an image and ask a question in English.

Worse: one normal satellite photo is often not enough.

- Clouds hide the ground.
- Night hides the ground.
- To know **what changed**, you need **before and after**.
- Radar (SAR) can see through clouds and at night, but it looks nothing like a photo. Optical and radar together are more reliable than either alone.

ChatGPT / Gemini looking at a screenshot is **not** the answer. Those models were trained on phone photos and the internet, not on GeoTIFFs, radar, and map coordinates. ISRO says a generic VLM **will not satisfy** this problem.

**What they want:** a website where a non-expert uploads satellite image(s), types a question, and gets:

1. a direct answer in English
2. proof drawn on the image / map
3. how sure the system is
4. a downloadable report
5. a visible log of which tool ran (not hidden “thinking”)

The special idea is **not** one giant model. It is a **manager** that picks the right specialist tool for the question and the images.

---

## 2. Forget the jargon. Here is the dictionary.

| Word they used | What it actually means |
|---|---|
| Remote sensing | Taking pictures of Earth from satellites |
| Optical / multispectral | Normal camera from space. Needs sunlight. Clouds block it. Looks like a coloured photo, sometimes with extra bands (infrared, etc.) |
| SAR (Synthetic Aperture Radar) | Radar from space. Works at night and through clouds. Looks grainy / black-and-white. Measures structure, not colour |
| Co-registered / aligned | Two images of the **same place**, lined up so pixel (100, 80) is the same spot on Earth in both |
| Bi-temporal | Same place, **two different dates** (before / after) |
| GeoTIFF / TIFF | Image file that also stores GPS / map information. This is the real satellite format |
| PNG / JPEG | Ordinary pictures. Allowed **only** for official benchmark samples, not as the main product |
| VQA | Visual Question Answering: user asks “Is there water here?” and the system answers from the image |
| Captioning | “Describe this scene in a sentence” |
| Grounding | “Highlight the water body mentioned in the question” — draw a box or mask |
| VLM | Vision-Language Model: an AI that reads images and text together (like GPT with eyes) |
| Fine-tune / adapt | Retrain or adjust that AI on **satellite** data so it stops treating Earth like a selfie |
| Agentic | A controller that **chooses and runs tools**, instead of one chatbot doing everything |
| Execution trace | A visible receipt: “I used change-detection tool v1, threshold 0.63, produced this mask” |
| Overlay | Coloured highlight drawn on top of the satellite image |
| Confidence | How sure the system is. If unsure, it should say so instead of guessing |
| CRS / transform / bands | Map projection, how pixels map to Earth, and how many colour/radar channels the file has |

You do **not** need to become a GIS expert. You **do** need to know that a satellite file is not “just a photo”.

---

## 3. Three kinds of upload. Memorise these.

Everything in the problem is one of these three modes.

### Mode A — One image
User uploads **one** optical or one SAR image.

Questions like:
- “Describe the land-cover and major objects visible in this image.”
- “Is there a water body here?”
- “Highlight the water body referred to in the query.”

**Mandatory:** answer questions about the image (VQA).
**Also mandatory:** pick **one extra** of:
- caption / scene description, **or**
- highlight the region they named (grounding).

For the prototype, pick **captioning**. It is easier than drawing accurate boxes.

### Mode B — Before and after (bi-temporal)
User uploads **two** images of the **same place**, different dates.

Questions like:
- “What changed between these two dates, and where did the change occur?”
- “Has the built-up area increased, decreased, or remained unchanged?”

**Mandatory.** This is one of the two things ISRO cares about most.

A chatbot looking at two screenshots side by side is **not** enough. You need a change specialist: compare the two images, say **what** changed, and mark **where**.

### Mode C — Optical + SAR of the same place
User uploads a **photo-like** image and a **radar** image of the same area, already aligned.

Questions like:
- “Use the optical and SAR images together to identify built-up and water-covered regions.”

**Mandatory.** The point is: clouds may hide buildings in the optical image; radar still sees structure. The system must use **both**, and you should be able to show that both contributed.

If your demo only uses the colour image and ignores radar, you fail this requirement.

---

## 4. What “agentic” means. This is the novelty.

Do **not** tell judges: “We fine-tuned one big model to do everything.”

Tell judges: **SatQuery AI is a manager over specialist tools.**

When a user asks a question, the manager does this, in order:

1. **Check the files.** Are they GeoTIFF? How many images? Optical or SAR? Same place? Same size? Dates present? If the pair is incompatible, **refuse and explain**. That refusal is a feature.
2. **Read the question.** Is this “describe this image”, “what changed”, or “use optical and SAR together”?
3. **Pick tools from a fixed list.** Not invent a new model on the fly. A registry:
   - single-image VQA
   - captioning
   - change VQA / change map
   - optical–SAR fusion
4. **Run only allowed settings.** Tile size, threshold, etc. No free-form dangerous parameters.
5. **Combine results.** Text answer + overlay + confidence. The text must come from the tool outputs, not from the LLM inventing extra objects.
6. **Show the receipt.** Task name, tool names, parameters, warnings, output files.

That receipt is what ISRO will evaluate. Hidden chain-of-thought does not count.

One-line pitch:

> ChatGPT guesses from a picture. SatQuery AI checks the satellite files, picks the right remote-sensing specialist, and shows evidence on the map.

---

## 5. The five things you must be able to demonstrate

ISRO wrote this as a checklist. If you miss one, the solution is incomplete.

| # | Must show | Simple demo that proves it |
|---|---|---|
| 1 | Adapted to satellite data, not phone photos | At least one vision/VLM piece trained or adapted on BigEarthNet (or another open satellite dataset). Keep the recipe and checkpoint. |
| 2 | Single-image Q&A | Upload one image. Ask “What land cover is visible?” Get an answer + confidence. |
| 3 | One extra single-image skill | Caption the scene, **or** highlight a named region. Captioning first. |
| 4 | Before/after change | Two dates. Answer what changed and **where**. Show a slider + red overlay. |
| 5 | Optical + SAR together | Toggle optical / SAR / fused. Show that fused is not identical to optical-only. |
| + | Manager (agent) | The UI shows which tool ran. Wrong/incompatible upload is rejected with a reason. |

A pretty chatbot that only does Mode A **does not win**.

---

## 6. How a user session actually looks

Walk this in your head. This is also your 2-minute video script.

1. Open the web app.
2. Choose mode: **Single image** / **Before + After** / **Optical + SAR**.
3. Upload the file(s). The system reads metadata (size, bands, map info, dates if present).
4. Preview appears on a map. Warnings if something is missing (“no date found — please enter it”).
5. Type a question in English.
6. The manager returns a plan, for example: `change_vqa → change_map → evidence_summary`.
7. Tools run. A change mask is produced.
8. Screen shows:
   - answer: “Built-up area increased along the river, about 12 hectares, confidence 0.74.”
   - overlay on the after-image
   - warnings if any
   - execution summary (tools + parameters)
9. Download PDF / JSON / GeoJSON report.

Then, on purpose, upload two images that are **not** the same place. The system says **no**, and explains why. That proves it is operational, not a toy.

---

## 7. Datasets — you do not need all of them by 12 Sep

These names look scary. Treat them as **homework for later**, except tiny samples now.

| Name | What it is | Why ISRO named it |
|---|---|---|
| **BigEarthNet** | Many small Sentinel-2 (optical) + Sentinel-1 (radar) patches of Europe, with land-cover labels | Train the model so it understands satellite optical **and** radar |
| **VRSBench** | Satellite images with questions, captions, and boxes | Test single-image Q&A, captions, highlighting |
| **RSVQA** | Another satellite Q&A set | Extra VQA test |
| **CDVQA** | Before/after pairs with change questions | Test “what changed?” |
| **ISRO/SAC hidden set** | Cartosat-2S optical + RISAT radar pairs. Labels **not** given to you | Final judging. You cannot train on this. Your system must generalise. |

Rules that will get you killed if you break them:

- Never train on official test splits.
- PNG/JPEG only for those public benchmark samples.
- Real geospatial path = GeoTIFF.
- Do not scrape random Google Earth screenshots and call it satellite AI.

For **12 Sep**, download a **few sample images** (one optical, one SAR, one before/after pair). You do not download terabytes this week.

---

## 8. What you are building as software (mental model)

Think of four layers. That is the whole architecture.

```
[ Website ]
   upload images, type question, see map, overlay, answer, log, download

[ Manager / API ]
   check files → classify question → pick tools → run them → fuse answer

[ Specialists ]
   A. single-image VQA + caption
   B. before/after change
   C. optical + SAR fusion

[ Geo engine ]
   read GeoTIFF, check alignment, make preview, convert pixel → map coords
```

For the **internal hackathon**, layers 1, 2, and 4 can be real. Layer 3 can be **honest stubs** plus one lightweight real model if you have time:

- Stub = a function that returns a structured answer and a fake overlay for **known demo images**.
- Real = a small open model that actually looks at the pixels.

Judges at college level want to **see the product**. ISRO at finale wants the models to be real. Do not confuse those two deadlines.

---

## 9. Two different products. Do not mix them up.

### Product for 10–12 September (internal)

Goal: college jury understands the idea and sees it working.

Must have:

- a 6-slide SIH-format PPT (use official template, PDF)
- a 2-minute video of the prototype
- a live demo that survives 8–10 minutes on stage

Prototype bar (realistic in ~10 days):

- working web UI with the 3 modes
- GeoTIFF upload + preview (PNG fallback for demo samples)
- question box
- manager that routes to the correct tool **and shows the log**
- three scripted scenes that always work
- one rejection scene (incompatible pair)
- answer + overlay + confidence + downloadable JSON
- models may be simple / stubbed **if you say so honestly** and the **workflow** is real

Prototype is **not**:

- training BigEarthNet from scratch
- beating VRSBench numbers
- a production GIS platform
- ChatGPT API with an upload button (that is the thing ISRO forbade)

### Product for SIH finale (later, if nominated)

Then you replace stubs with adapted models, run official splits, keep checkpoints, write model cards, and make the demo work offline.

You cannot finish the finale product by 12 Sep. Anyone who tries will have no PPT, no video, and a broken demo.

---

## 10. The three demo scenes you will live or die on

Lock these now. Video, PPT, and live talk all use the same three.

**Scene 1 — Single image (30–40s)**
- Upload one optical image of a mixed landscape.
- Ask: “Describe the land-cover and major objects visible in this image.”
- Show caption + VQA answer + heatmap/overlay + tool log.

**Scene 2 — Before / after (40–50s)**  ← strongest scene
- Upload 2018 and 2024 of the same city edge or river.
- Ask: “Has the built-up area increased, decreased, or remained unchanged?”
- Show slider, red change overlay, area number, confidence.

**Scene 3 — Optical + SAR (30–40s)**
- Use a cloudy or flood-like pair.
- Ask: “Use the optical and SAR images together to identify built-up and water-covered regions.”
- Toggle optical / SAR / fused. Say out loud what SAR added (e.g. water under cloud).

**Bonus 10s:** upload a mismatched pair. System refuses. “We do not hallucinate alignment.”

If those four clips work, your video is done.

---

## 11. PPT (6 slides, official template) — what each slide must say

Use the **official SIH idea template**. Max 6 slides including title. Export PDF. No paragraphs.

**Slide 1 — Title**
PS ID SIH26167, full title, theme Space Technology, category Software, team ID, registered team name.

**Slide 2 — Proposed solution**
One sentence: *SatQuery AI lets a non-GIS user ask English questions on single, before/after, and optical–SAR satellite images, and get an evidence-backed answer.*
Then 4 bullets: manager (not one VLM), 3 input modes, evidence + confidence, reject bad inputs.
Uniqueness: specialist tools + visible execution trace. Not ChatGPT-on-images.

**Slide 3 — Technical approach**
One flowchart: Upload → Validate → Route → Specialist → Fuse → Report.
Tech: React + map, FastAPI, rasterio/GDAL, PyTorch specialists, BigEarthNet adaptation later.
Screenshot of prototype if you have it.

**Slide 4 — Feasibility**
Can build UI + manager + geo checks now. Models: start with stubs + one adapted baseline, then swap in specialists.
Risks: GPU, hallucination, SAR treated as RGB, unaligned pairs. Mitigations: PEFT, structured outputs, modality-specific pre-process, reject bad pairs.

**Slide 5 — Impact**
Users: ISRO/NRSC analysts, disaster cells, urban bodies, agriculture/water departments.
Impact: faster flood/urban-change answers without a GIS specialist in the loop. Evidence trail for audit.

**Slide 6 — References**
Problem statement, BigEarthNet, VRSBench, RSVQA, CDVQA, Sentinel-1/2, MapLibre/rasterio.

---

## 12. 2-minute video script (speak this)

0:00–0:15 Problem
“Satellite images are used for floods, cities, and farms, but today’s tools are single-task and need GIS experts. One optical photo is often not enough — clouds, night, and change need radar and before/after pairs.”

0:15–0:30 Solution
“SatQuery AI is a web assistant. Upload GeoTIFFs, ask in English. A controller checks the files, picks a remote-sensing specialist, and returns an answer with a map overlay, confidence, and an audit log. Not a generic chatbot.”

0:30–1:50 Demo (the three scenes + reject)
Live screen recording. No background music drowning speech. Show the execution log in every scene.

1:50–2:00 Close
“Single-image VQA, change analysis, optical–SAR fusion, and agentic routing — in one operational tool for ISRO.”

Record the demo twice. Keep a backup screen recording on a second laptop for 12 Sep.

---

## 13. Day-by-day until 12 Sep (leader view)

Today is 1 Sep. You have 9 days to upload, 11 days to present.

| When | What must exist by end of day |
|---|---|
| **1–2 Sep** | You understand this brief. Team agrees on 3 demo scenes. Roles assigned. GitHub repo. UI wireframe. Sample images collected. |
| **3–5 Sep** | Working UI: 3 modes, upload, question box, map preview. Manager returns a real JSON plan. Stubs return structured answers + overlays for the 3 scenes. |
| **6–7 Sep** | GeoTIFF metadata check + incompatible-pair rejection. Downloadable JSON. One lightweight real inference if GPU exists, else keep stubs and label them. PPT draft in official template. |
| **8 Sep** | Freeze demo scenes. Full rehearsal. Record video. |
| **9 Sep** | Edit video. Finish PPT. Faculty review. Fix bugs only. |
| **10 Sep** | Upload PPT + 2-min video. Do not touch code after upload except for 12 Sep backup. |
| **11 Sep** | Dry run of live talk. Backup laptop, local samples, offline mode. |
| **12 Sep** | Present. Demo the 3 scenes + reject. You speak problem + uniqueness. One member drives the laptop. |

If you are behind on 6 Sep, **cut real training**. Ship the workflow. A working manager with stubs beats a half-trained model with no UI.

---

## 14. Questions judges will ask you, and answers

**“How is this not ChatGPT + image upload?”**
ChatGPT does not validate GeoTIFFs, does not distinguish SAR from optical, does not align pairs, does not produce a change mask in map coordinates, and is not adapted on BigEarthNet. We route to specialists and show the tool receipt.

**“Did you train anything?”**
Internal: we adapted / will adapt a vision component on BigEarthNet; the app already runs the agentic workflow. Finale: published checkpoints and benchmark scores. Do not lie. If it is a stub, say “workflow is live, model weights are the next milestone.”

**“What if the two images are not the same place?”**
We reject. We do not silently warp and guess.

**“How do you know both optical and SAR were used?”**
We run optical-only, SAR-only, and fused, and show the difference. Ablation is the proof.

**“Where is the evidence?”**
Every answer has an overlay or coordinates plus confidence. Text without a mask is incomplete.

**“What about Cartosat and RISAT? You don’t have that data.”**
Final ISRO set is hidden. We train on open Sentinel-1/2 (BigEarthNet) and design the pipeline so any co-registered optical–SAR GeoTIFF can go through the same validator. That is the point.

---

## 15. What you, as leader, must lock before dividing work

Do not assign members until these are decided. They take one meeting.

1. **Team name** (no college name inside it) and who speaks on 12 Sep.
2. **The 3 demo scenes** and the exact questions you will ask on stage.
3. **Captioning vs grounding** as the extra single-image task → choose captioning.
4. **Who has a GPU**, Google Colab Pro, or a college lab machine.
5. **Frontend:** simple React web app (recommended) vs Gradio (faster, uglier). For jury, React looks more like a product.
6. **Honesty line** for stubs vs real models, so nobody contradicts on stage.

After that meeting, *then* split into 6 roles.

---

## 16. One sentence you should be able to say without notes

> We are building a website for ISRO where a non-expert uploads one satellite image, a before/after pair, or an optical+radar pair, asks a question in English, and a controller picks the right remote-sensing tool and returns an answer drawn on the map — not a generic chatbot guessing from a screenshot.
