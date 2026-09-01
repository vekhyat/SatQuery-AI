# 6-person split — internal hackathon (1–12 Sep)

Nobody is assigned “train a VLM.”
Nobody is assigned “build an LLM router.”

You are six people building **one desk**: website, file checker, router, three tools, PPT, video.

**You (leader) = Member 1.** You already understand the architecture. You own the router (the idea) and you speak on 12 Sep.

Fill real names in the table today. After that, people only touch their box plus the shared schema.

---

## Who does what

| # | Role | Put this person | Owns | Does **not** do |
|---|---|---|---|---|
| **M1 You** | **Desk + pitch** | Leader. Strongest at “how the whole thing fits.” | API, JSON schemas, router (if-then), composer, execution receipt, GitHub, daily sync, **12 Sep talk**, PPT story | Pretty UI, training models |
| **M2** | **Website** | Best frontend person | 3-mode UI, upload, map, overlay, slider, Optical/SAR toggle, log panel, download button | Backend logic, models |
| **M3** | **Checker + samples** | Comfortable with Python files / GIS curiosity | GeoTIFF read, metadata, “same place?”, reject reasons, **the 3 demo image packs** | UI, routing rules |
| **M4** | **Single-image room** | Some ML or okay Python | Tool 1: labels + caption template + heatmap. **Demo scene 1 always works** | Change, fusion, PPT |
| **M5** | **Change room** | Strongest remaining Python/ML | Tool 2: before/after compare, red mask, area, increased/decreased. **Demo scene 2 always works** (this is the hero scene) | UI, fusion |
| **M6** | **Fusion room + film** | Remaining member; can be decent Python + organised | Tool 3: optical map + SAR map + fused + toggle proof. **Demo scene 3 always works.** Records/edits the **2-min video** with M2 | Router, talk |

**PPT:** M1 writes the words. M2 / M6 put it on the official 6-slide template. Freeze 9 Sep.

**Laptop driver on 12 Sep:** M2. **Speaker:** M1. **Backup laptop + samples:** M3.

---

## The contract between you (do this on 1–2 Sep)

Everyone returns the **same JSON shape**. If they don’t, the website cannot show a result.

M1 publishes this on day 1. Nobody invents their own format.

```json
{
  "task": "single_image | change | optical_sar | reject",
  "tools": ["..."],
  "parameters": {},
  "facts": {},
  "answer_text": "one or two sentences from facts only",
  "confidence": 0.0,
  "warnings": [],
  "overlay": { "type": "heatmap | change_mask | none", "file": "..." },
  "receipt": { "why_this_tool": "...", "rejected": false, "reason": null }
}
```

M4, M5, M6 only fill `facts`, `confidence`, `overlay`.  
M1’s composer writes `answer_text`.  
M2 only displays fields. It does not think.

---

## Member 1 — You (desk + pitch)

**Build**
- Repo, folders, README, `.gitignore` (no huge TIFFs in git)
- FastAPI: `POST /upload`, `POST /query`
- Pydantic schemas above
- Router:
  - 1 image → `single_image`
  - 2 images, different dates → `change`
  - 1 optical + 1 SAR → `optical_sar`
  - else → `reject`
- Composer: template sentences from facts
- Glue: call M3 then M4/M5/M6 then return JSON to M2

**Pitch**
- 6-slide story (not decoration)
- 2-min voiceover script
- 12 Sep: problem → 3 scenes → “this is not a chatbot”

**Done when:** Postman can hit `/query` for all 3 modes + reject, without the UI.

---

## Member 2 — Website

**Build**
- Mode picker: Single / Before-After / Optical+SAR
- Upload + question box + Run
- Map or image viewer
- Show answer, confidence, warnings
- Show **receipt** (tool name + settings) — judges must see this
- Before/after **slider**
- Optical / SAR / Fused **toggle**
- Download JSON
- Empty and error states (rejected pair)

**Done when:** Fake JSON from M1 already looks like the real product. Then swap fake for live API.

Use dummy JSON on day 2. Do not wait for models.

---

## Member 3 — Checker + demo files

**Build**
- Open GeoTIFF, print: size, bands, CRS, bounds, dates if any
- Decide optical vs SAR (or ask user if unknown)
- Pair check: same place? same size/grid? if not → reject string
- Make PNG previews for the UI
- Collect **four packs** (small files, known answers):
  1. One optical landscape
  2. Before/after of a city edge or river (change is visible)
  3. Cloudy optical + SAR of same place
  4. Two images that are **not** the same place (for reject)

**Done when:** a script prints `OK` or `REJECT: reason` for those four packs. M2 can show previews.

---

## Member 4 — Single-image tool (scene 1)

**Build a function, not a chatbot.**

```
image → { labels: ["water","forest"], caption_bits: [...], heatmap optional, confidence }
```

Simplest legal version:
- pretrained satellite land-cover if you find one, **or**
- a tiny classifier, **or**
- for 12 Sep: a **stub that is correct on the chosen demo image** plus a real heatmap-ish overlay

Caption = `"This scene contains: " + labels`.

Scene 1 question (lock it):  
*“Describe the land-cover and major objects visible in this image.”*

**Done when:** that one image always returns the same JSON in < 10s.

---

## Member 5 — Change tool (scene 2, hero)

```
before, after → { answer_key: increased|decreased|unchanged, area_ha, mask, confidence }
```

Simplest version: align (M3 already checked), subtract, threshold, paint red, count pixels → hectares.

Scene 2 question (lock it):  
*“Has the built-up area increased, decreased, or remained unchanged?”*

**Done when:** slider + red overlay + “increased” (or whatever is true for your pair) never fails.

---

## Member 6 — Optical+SAR tool + video

```
optical, sar → { fused_labels, optical_only, sar_only, note: "SAR added water under cloud" }
```

Simplest version: two separate maps + a combine rule (e.g. water if *either* says water). UI toggle is the proof.

Scene 3 question (lock it):  
*“Use the optical and SAR images together to identify built-up and water-covered regions.”*

**Video (with M2)**
- 0:00–0:15 problem (M1 voice)
- 0:15–0:30 “not a chatbot, a desk” (M1)
- 0:30–1:50 three scenes + reject (screen)
- 1:50–2:00 close

**Done when:** toggle Optical / SAR / Fused shows they are not identical, and a 2-min cut exists by 9 Sep.

---

## Calendar (today = 1 Sep)

| Day | Everyone | Extra |
|---|---|---|
| **1 Sep** | Names in this table. Schema from M1. Scene images chosen by M3. | Repo live |
| **2 Sep** | M2 dummy UI. M1 dummy `/query`. M3 first samples. M4–6 function signatures | |
| **3–4 Sep** | Wire UI ↔ API with dummy tools | Checker rejects pack 4 |
| **5 Sep** | **First full run** of 3 scenes + reject, even if tools are stubs | |
| **6–7 Sep** | Make overlays look real. Composer sentences. JSON download | PPT draft |
| **8 Sep** | **Freeze scenes.** No new features. Record video | |
| **9 Sep** | Edit video. PPT on official template. Rehearse 10 min | |
| **10 Sep** | **Upload PPT + video** | Stop feature work |
| **11 Sep** | Dry run, backup laptop, offline samples | |
| **12 Sep** | Present | M1 talks, M2 drives |

If 5 Sep is not green, **cut tool quality, not the pipeline.** Stubs on known images beat a half-trained model with no screen.

---

## Daily 20-minute stand-up (M1 runs it)

1. Can the 3 scenes run end-to-end today? yes/no  
2. Blocker in one sentence  
3. What you will merge before tomorrow  

No one works in a private folder until the night before.

---

## 12 Sep script (who does what on stage)

| Time | Who | What |
|---|---|---|
| 0:00–1:30 | M1 | Problem: GIS tools are siloed; one photo is not enough; we built a desk not a chatbot |
| 1:30–6:00 | M2 drives, M1 talks | Scene 1, 2, 3. Point at the **receipt** every time |
| 6:00–7:00 | M2 | Reject mismatched pair |
| 7:00–8:00 | M1 | Architecture in one diagram (checker → router → one tool → map) |
| 8:00–10:00 | all | Questions. If they say “VLM?”: “The router is code. Specialists are tools. We don’t run a chatbot.” |

---

## Names (fill today)

| Role | Name |
|---|---|
| M1 Desk + pitch (you) | |
| M2 Website | |
| M3 Checker + samples | |
| M4 Single-image | |
| M5 Change | |
| M6 Fusion + video | |

If two people are only frontend: M2 and help M6 with video/PPT, do not invent a second UI.  
If two people only know ML: M4 and M5; fusion (M6) can stay rule-based.  
If nobody knows GIS: M3 still only reads file headers with rasterio — not a full GIS career.
