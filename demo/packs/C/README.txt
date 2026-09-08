Pack C - Optical + SAR, Tool 3 / M6

Generate the synthetic demonstration from the repository root:
  python -m satquery.tools.tool3.pack_c demo/packs/C/generated

Upload these two files through the normal website or POST /upload:
  generated/optical.tif
  generated/sar.tif

Both are 32 x 32 pixels, EPSG:32643, 10 m pixels, date 2026-01-01.
Optical band descriptions: red, green, blue, nir, swir.
SAR band descriptions: vv, vh. Band units: linear power.

Ask: Use the optical and SAR images together to identify built-up and
water-covered regions.

Expected behavior: optical-only, SAR-only and fused maps; SAR contributes
additional water and built-up candidates, including the rectangles on the
right of the image. The default filtering affects region boundaries.
Confidence must be described as not calibrated / not measured.

The generator also creates individual bands and a manually defined reference
map under generated/bands. The reference has 128 water pixels and 144 built-up
pixels. Those are synthetic reference labels, not satellite accuracy scores.

Provenance/licensing: generated numeric fixtures, no third-party imagery is
distributed. Before substituting real satellite scenes, M3 must record their
source, acquisition dates, calibration, and applicable licence here.

generated/ is gitignored. Do not commit the generated TIFFs or runtime results.
The generator refuses to overwrite an existing output directory; use a new
directory when another copy is needed.
