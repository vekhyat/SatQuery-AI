# Tool 3 algorithm and independent manifest reference

Read [TOOL3_HANDOFF.md](TOOL3_HANDOFF.md) for the integrated upload/query API. This reference describes the processing core and its offline result envelope. Run from the repository root using `python -m satquery.tools.tool3 --manifest YOUR_MANIFEST.json --output-dir runtime/tool3`.

## Input bands and physical measurements

| Role | Requirement | Typical Sentinel-2/1 input |
|---|---|---|
| `green` | Required; reference output grid | B03 |
| `nir` | Required | B08 |
| `swir` | Required | B11 |
| `vv` | Required; calibrated power or dB | VV |
| `vh` | Optional; strengthens SAR evidence | VH |
| `red` | Optional; enables NDVI vegetation suppression | B04 |
| `blue` | Optional; with red enables a natural-colour preview | B02 |
| `scl` | Optional; Sentinel-2 scene classes 0–11 | SCL |
| `valid_mask` | Optional; positive = clear/usable optical, 0 = excluded | Custom quality mask |

Supported inputs are real-valued georeferenced rasters readable by Rasterio; automatic discovery scans `.tif`, `.tiff`, and `.jp2`. Multiband auto-discovery requires descriptive band names. Unknown/ambiguous band names require a manifest. Multiple candidates for the same role are rejected rather than selecting an arbitrary date or resolution. Archives must be extracted first. One manifest represents one scene pair; use `--batch` for multiple pairs.

All optical bands must use compatible reflectance values or a common multiplicative scale with zero offset. A band mapping may include `scale`, `offset`, and `nodata`; corrections use `physical = raw * scale + offset`. Overrides replace the corresponding raster metadata values. In particular, `nodata` replaces a header sentinel, while explicit internal/dataset/alpha masks are still respected. This supports correcting a file that incorrectly marks valid zero-dB pixels as nodata. For native products with additive DN offsets, provide their actual calibration; the tool does not infer product XML calibration. Do not copy Sentinel-2 band numbers onto another sensor without checking the spectral bands.

SAR must already be calibrated and orthorectified/terrain-corrected as appropriate. Select `--sar-units linear` for positive **linear power**, or `--sar-units db` for calibrated decibels (negative and zero dB are valid). Raw amplitude, complex SLC, uncalibrated DN, arbitrary RGB screenshots, and optical imagery without NIR/SWIR are unsupported. HH/HV are not treated as VV/VH automatically.

Auto SAR units use explicit raster unit metadata, a `DB` filename token, or the known floating-point Copernicus Browser `Sentinel-1 ... (Raw)` naming convention. Naming-based inferences are logged as warnings. Otherwise the tool requests an explicit setting rather than guessing from pixel brightness. Per-band manifest units take precedence over the global setting and support stacks exported with different units.

## Processing and configuration

1. Validate files, band indexes, CRS, nondegenerate affine transform, sample types, dates, and pixel limits. Distinct dates within one sensor are rejected; a known optical/SAR gap over 30 days is rejected by default. Missing dates are reported.
2. Apply GDAL/raster masks, nodata, finite-value checks, and calibration before resampling. Use the green band's CRS, bounds, transform, and dimensions as the output grid. Optical values use bilinear reprojection; SAR uses average resampling in **linear power**; mask coverage uses nearest neighbour. Supplied quality masks are mapped to each optical band's native grid and applied **before interpolation**, then applied again on the output grid. This prevents excluded cloud samples from contaminating adjacent clear pixels. Reading optical bands again for this step adds I/O only when a quality mask is supplied. Sources are never resized merely to match array dimensions.
3. Compute NDWI `(green - NIR)/(green + NIR)` for water and NDBI `(SWIR - NIR)/(SWIR + NIR)` for built-up candidates. Defaults are index > 0. When red exists, exclude optical built-up where NDVI > 0.3. Invalid/zero denominators stay nodata. SCL keeps classes 2, 4, 5, 6; other classes are excluded. Without quality data, clouds/shadows are not identified.
4. Apply a masked 3×3 mean to aligned SAR power, then convert with `10*log10(power)`. Default water limits are `min(VV p15, -17 dB)` and `min(VH p20, -23 dB)`. Default built-up limits are `max(VV p80, -8 dB)` and `max(VH p70, -15 dB)`. Water requires values <= both available limits; built-up requires values >= both. These guards avoid forcing a fixed detection percentage but still require scene validation. Explicit dB thresholds replace the defaults.
5. Open/close masks with a 3×3 kernel and remove components smaller than 9 output pixels. Reapply validity during cleanup. `min_component_m2` can also set a minimum projected area; the greater of the pixel and area limits applies.
6. Require SAR to cover at least 50% of jointly valid optical index pixels **before quality masking**. An entirely cloudy optical image can still use valid SAR evidence. Outside common coverage, use whichever sensor is valid. Within the optical reference footprint, union water first, then union built-up excluding water. SAR outside that footprint is not included.
7. Count what SAR actually added after resolving class conflicts. An identical fused result is reported honestly; the tool never fabricates differences for the demo. Sensor agreement is a diagnostic, not accuracy.

Useful overrides (all available in a manifest's `parameters` too):

```powershell
python -m satquery.tools.tool3 --sar-units db --sar-water-vv-db -18 --sar-water-vh-db -24
python -m satquery.tools.tool3 --ndwi-threshold 0.05 --ndbi-threshold 0.1 --vegetation-threshold 0.3
python -m satquery.tools.tool3 --min-component-m2 500 --morphology-size 3
python -m satquery.tools.tool3 --speckle-size 1 --morphology-size 1 --min-component-pixels 0
python -m satquery.tools.tool3 --help
```

`1` disables each filter; `0` disables the pixel component minimum. Kernels must be odd integers 1–31. Default `max_pixels` is 16,000,000 **per source raster**. Processing uses in-memory arrays; crop large scenes to the study area. Raising this limit does not enable streaming and may require substantial RAM. No automatic cropping or silent downsampling is performed.

## Results and integration

Each success writes a unique `output/<UTC timestamp>_<id>/` directory. `output/latest.json` points to the newest successful result and report. Previous results are retained; each new invocation returns its own run paths.

| Artifact | Meaning |
|---|---|
| `report.html` | Offline Optical/SAR/Fused toggles, preview toggles, counts, warnings, download links |
| `result.json` | Handbook envelope with `facts`, `confidence`, `overlay`, `layers`, and processing receipt |
| `optical_only`, `sar_only`, `fused` `.png`/`.tif` | Three candidate class maps on one georeferenced grid |
| `*_water_mask`, `*_builtup_mask` `.png`/`.tif` | Six optical/SAR/fused binary masks |
| `ndwi.tif`, `ndbi.tif`, optional `ndvi.tif` | Optical index rasters |
| `sar_vv_db.tif`, optional `sar_vh_db.tif` | Aligned, smoothed SAR evidence in dB |
| `optical_preview.png`, `sar_preview.png` | Percentile-stretched previews; never used for classification |

Class GeoTIFF values: **0 other/unclassified, 1 water candidate, 2 built-up candidate, 255 nodata**. Binary GeoTIFF values: **0 negative, 1 positive, 255 nodata**. Index/dB nodata: **-9999**. PNG masks use white detections, black negative pixels, and transparent nodata. Use GeoTIFFs for GIS analysis, not PNG resizing.

Counts are exact for these generated masks. Areas use the determinant of the projected grid transform and its linear-unit conversion, and are only grid estimates. They do not correct projection distortion. Geographic CRS outputs have null hectare values rather than treating degrees as metres.

The numeric `confidence` is `0.0` to retain the handbook's numeric contract. This is an **uncalibrated placeholder**, not 0% measured accuracy. Read `facts.confidence_status`. A later trained/calibrated model can replace this value after labelled evaluation. The local wrapper fills `answer_text` and `receipt` for standalone use; the team's composer/router may replace these fields.

The receipt also records input file sizes/modification times and the Tool 3, Python, NumPy, Rasterio, GDAL, and OpenCV versions. These help reproduce runs; they are not cryptographic content hashes.

## Measure accuracy when independent reference labels are available

```powershell
tool3-evaluate --prediction "output\RUN_ID\fused.tif" --reference "labels\reference.tif" --output "evaluation.json"
```

Both files must be single-band class maps with **0 other, 1 water, 2 built-up**, and nodata outside labelled/observed areas. Use independently labelled data, not the detector's own output as its reference. The reference is resampled with nearest neighbour onto the prediction grid. Convert other dataset label conventions explicitly before evaluation. A nodata sentinel of 0/1/2 conflicts with this class legend; correct the metadata, or use `--reference-nodata 255` when that is the actual reference sentinel.

Evaluation reports the confusion matrix (reference rows, prediction columns), accuracy, per-class precision/recall/F1/IoU, mean IoU, macro F1, and prediction coverage of reference labels. Undefined metrics for absent classes are null. Scores use jointly valid pixels on the prediction grid, and missing predictions are counted separately so low coverage cannot be mistaken for complete scene coverage. Existing evaluation JSON files are not overwritten. These scores assess the supplied labels only and do not automatically change the detector's confidence or establish performance on new scenes.
