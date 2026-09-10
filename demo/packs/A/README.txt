Pack A - Single Image Land-Cover Analysis (Tool 1)

This folder contains the frozen demonstration fixture for Tool 1.

Files:
  Pack_A_01.tif

Specifications:
  - Dimensions: 64 x 64 pixels
  - CRS: EPSG:32643
  - Pixel size: 10 m
  - Acquisition Date: 2026-01-01
  - Modality: Optical
  - Bands (4):
      Band 1: blue
      Band 2: green
      Band 3: red
      Band 4: nir

Pack A Card Labels:
  - water
  - vegetation
  - built-up

Expected Output:
  - Water detected (via NDWI): Yes
  - Vegetation detected (via NDVI): Yes
  - Built-up detected (via brightness): Yes
  - Deterministic Card Labels: ["water", "vegetation", "built-up"]
  - Caption: "This scene contains: water, vegetation, built-up."
  - Overlay: Heatmap highlighting water (blue), vegetation (green), built-up (red).

How to run:
  Upload Pack_A_01.tif in the SatQuery UI or via POST /upload.
  Ask: "Describe the land-cover and major objects visible in this image."
  Or ask: "Is there water present in this image?" -> Answer: "yes"

To regenerate the fixture:
  python -m satquery.tools.pack_a
