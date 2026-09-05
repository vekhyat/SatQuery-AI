# SatQuery AI design system

Source of truth: the shipped Query Notebook in `apps/web`. React with Python is the stack.

## Identity

Query Notebook joins the question, satellite imagery, and evidence receipt in one investigation. Keep the left scene index, wide image strip, and three-stage receipt. This is an operator workspace.

## Color and typography

- Page `#f7f9f9`; header `#f4f7f7`; sidebar `#f1f5f5`.
- Ink `#153e48`; secondary ink `#5b6b70`; rules `#d5dfe0`.
- Action `#bd422a`; selected investigation `#e0eae8`; result ground `#eaf0ee`.
- Self-hosted DM Sans Variable. Headings 29–42px with -0.033em tracking; primary controls 12–16px. Monospace is reserved for JSON/data.
- Flat surfaces, 1px rules, 4–5px corners, consistent light Lucide strokes.

## Composition and behavior

70px desktop header, 252–280px sidebar, fluid notebook with 24–42px margins. Sequence: heading, question, read-only route status, viewer controls, imagery, answer, collapsed receipt. The API chooses the route; indicators must never become manual mode selectors. A new investigation shows a large Add scenes dropzone under the question; later attaches stay in the sidebar.

A demo change finding uses a pin on the after plate and a 1px leader into the answer. Rejected inputs and live stubs have no pin. Say “illustrative” once in the header; the result prefix can repeat it, nothing else should.

On mobile the sidebar opens from a labelled Investigations control, the query and action stack, image panels keep an explicit height, and the receipt stays collapsed until opened. Hide the leader on small screens; keep the pin. Viewer controls expose pressed states; comparison sliders work with a keyboard.

Border Beam belongs to question focus/loading. Thinking Orbs marks waiting; it never simulates hidden intermediate server progress. Reduced motion disables animation.

## Truth and state

Demo examples load prepared scenes and questions and remain labelled illustrative. Real uploads show actual raster previews. Rejected inputs have no overlay; stubs state analysis is not connected. Confidence is not measured for demos/stubs. Receipt stages, tools, parameters, warnings and result downloads come from JSON.

## Assets

`public/assets/river-pair.png` is a generated diptych for demo scenery. Its prompt is embedded and saved alongside it. Uploaded thumbnails come from Python raster processing. All text, controls, icons and routing geometry remain semantic code.
