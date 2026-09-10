Pack A - Single Image Land-Cover Analysis (Tool 1)

This folder contains the frozen demonstration fixture for Tool 1.

Files:
  Pack_A_01.tif

Specifications:
  - Dimensions: 64 x 64 pixels
  - CRS: EPSG:32643 (UTM zone 43N)
  - Origin: 500000 E, 3100000 N (valid UTM 43N origin)
  - Pixel size: 10 m
  - Acquisition Date: 2026-01-01
  - Modality: Optical
  - Bands (4):
      Band 1: blue
      Band 2: green
      Band 3: red
      Band 4: nir

Pack A Card (synthetic rectangles in the fixture):
  - water
  - vegetation
  - built-up

Expected Output:
  - Water detected (via NDWI): Yes
  - Vegetation detected (via NDVI): Yes
  - Built-up detected (via brightness, after excluding water and vegetation pixels): Yes
  - Labels come from detector has_* flags, not the filename.
  - If the filename matches Pack A but a detector misses a class, a warning is appended.
  - Caption: "This scene contains: water, vegetation, built-up."
  - Overlay: Heatmap highlighting water (blue), vegetation (green), built-up (red).
    Overlay classes match caption labels (a class is drawn only when its has_* flag is True).

How to run:
  Upload Pack_A_01.tif in the SatQuery UI or via POST /upload.
  Ask: "Describe the land-cover and major objects visible in this image."
  Or ask: "Is there water present in this image?" -> Answer: "yes"

To regenerate the fixture, run from the repository root:
  python -m satquery.tools.pack_a

The default output path is resolved from the repository root
(demo/packs/A/Pack_A_01.tif), not the current working directory.
