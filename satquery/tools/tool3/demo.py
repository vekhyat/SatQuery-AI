"""Create a small, portable synthetic scene with hand-defined reference labels."""
import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


def create_demo(directory):
    """Create a NEW directory, never overwrite existing datasets or outputs."""
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    values = {"green": .12, "nir": .3, "swir": .2, "red": .1, "blue": .08, "vv": .1, "vh": .025}
    bands = {role: np.full((32, 32), value, dtype=np.float32) for role, value in values.items()}
    for role, value in (("green", .3), ("nir", .05), ("swir", .02), ("red", .02)):
        bands[role][3:11, 3:11] = value
    for role, value in (("green", .1), ("nir", .2), ("swir", .4), ("red", .2)):
        bands[role][18:27, 3:11] = value
    for role, dark, bright in (("vv", .001, .8), ("vh", .0003, .2)):
        bands[role][3:11, 3:11] = dark
        bands[role][3:11, 18:26] = dark
        bands[role][18:27, 18:26] = bright
    reference = np.zeros((32, 32), dtype=np.uint8)
    reference[3:11, 3:11] = reference[3:11, 18:26] = 1
    reference[18:27, 3:11] = reference[18:27, 18:26] = 2
    for role, data in {**bands, "reference": reference}.items():
        with rasterio.open(root / f"{role}.tif", "w", driver="GTiff", count=1,
                           height=32, width=32, dtype=data.dtype, crs="EPSG:32643",
                           transform=from_origin(500000, 3100000, 10, 10),
                           nodata=255 if role == "reference" else None) as dst:
            dst.write(data, 1)
            dst.set_band_description(1, role)
            dst.update_tags(ACQUISITION_DATE="2026-01-01", provenance="SYNTHETIC software test; not satellite observations")
    request = {"bands": {role: {"path": f"{role}.tif", **({"units": "linear"} if role in ("vv", "vh") else {})} for role in bands},
               "parameters": {"morphology_size": 1, "speckle_size": 1, "min_component_pixels": 1}}
    for name, data in (("manifest.json", request),
                       ("catalog.json", {"datasets": {"synthetic": "manifest.json"}}),
                       ("expected.json", {"synthetic_only": True, "sar_added_water_pixels": 64,
                                          "sar_added_builtup_pixels": 72, "water_pixels": 128, "builtup_pixels": 144})):
        (root / name).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return root / "manifest.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="New directory to create (must not exist).")
    args = parser.parse_args(argv)
    try:
        manifest = create_demo(args.directory)
    except OSError as exc:
        parser.exit(2, f"Cannot create demo: {exc}\n")
    print(f"Synthetic demo created: {manifest}")
    print(f'tool3 --manifest "{manifest}" --open-report')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
