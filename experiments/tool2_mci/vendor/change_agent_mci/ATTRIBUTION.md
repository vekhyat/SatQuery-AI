# Attribution

The model architecture modules and LEVIR-MCI vocabulary in this directory are derived from Change-Agent by Chen-Yang-Liu:

- Upstream project: https://github.com/Chen-Yang-Liu/Change-Agent
- Upstream component: Multi_change
- License: MIT; the complete license text is included in LICENSE.txt.

Local compatibility changes are intentionally limited to device-aware tensor allocation, removal of unused mmcv/mmseg imports, and omission of preliminary MiT weights that are superseded by the externally supplied full MCI checkpoint. No lagent, Streamlit, training, evaluation, search, or OpenAI integration code is included.

