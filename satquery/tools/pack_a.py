"""Generate upload-ready synthetic GeoTIFF stack for Tool 1 (Pack A)."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


def create_pack_a(destination_file: Path | str) -> Path:
    """Generates a frozen 4-band GeoTIFF with water, vegetation, and built-up areas."""
    dest = Path(destination_file).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    width = 64
    height = 64
    transform = from_origin(77.0, 29.0, 10.0, 10.0)

    # Initialize 4 bands with baseline values (Blue, Green, Red, NIR)
    blue = np.full((height, width), 60, dtype=np.uint8)
    green = np.full((height, width), 70, dtype=np.uint8)
    red = np.full((height, width), 80, dtype=np.uint8)
    nir = np.full((height, width), 80, dtype=np.uint8)

    # Water area (top-left): high green, low NIR -> NDWI > 0.20
    blue[0:25, 0:25] = 120
    green[0:25, 0:25] = 140
    red[0:25, 0:25] = 40
    nir[0:25, 0:25] = 10

    # Vegetation area (bottom-left): high NIR, low red -> NDVI > 0.30
    blue[35:60, 0:30] = 30
    green[35:60, 0:30] = 100
    red[35:60, 0:30] = 30
    nir[35:60, 0:30] = 200

    # Built-up area (right side): high brightness across visible spectrum -> brightness > 0.70
    blue[10:45, 35:60] = 220
    green[10:45, 35:60] = 220
    red[10:45, 35:60] = 230
    nir[10:45, 35:60] = 210

    bands_data = [blue, green, red, nir]
    descriptions = ["blue", "green", "red", "nir"]

    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": 4,
        "dtype": "uint8",
        "crs": "EPSG:32643",
        "transform": transform,
    }

    with rasterio.open(dest, "w", **profile) as dst:
        for idx, (b_data, desc) in enumerate(zip(bands_data, descriptions, strict=True), start=1):
            dst.write(b_data, idx)
            dst.set_band_description(idx, desc)
        dst.update_tags(
            MODALITY="optical",
            ACQUISITION_DATE="2026-01-01",
            SENSOR="Sentinel-2",
            PACK="Pack A",
            PACK_CARD="water, vegetation, built-up",
            PROVENANCE="Synthetic demonstration fixture for Tool 1 single-image analysis",
        )

    return dest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("demo/packs/A/Pack_A_01.tif"),
        help="Path to generate Pack A GeoTIFF",
    )
    args = parser.parse_args(argv)
    output_path = create_pack_a(args.output)
    print(f"Pack A GeoTIFF created successfully at {output_path}")


if __name__ == "__main__":
    main()
