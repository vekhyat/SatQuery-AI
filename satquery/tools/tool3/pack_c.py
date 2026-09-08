"""Generate two upload-ready synthetic stacks for the team's Pack C demo."""
import argparse
import json
from pathlib import Path

import rasterio

from .demo import create_demo


def create_pack(directory):
    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    manifest = create_demo(root / "bands")
    groups = {"optical": ("red", "green", "blue", "nir", "swir"), "sar": ("vv", "vh")}
    for sensor, roles in groups.items():
        with rasterio.open(manifest.parent / f"{roles[0]}.tif") as src:
            profile = src.profile.copy()
        profile.update(count=len(roles))
        with rasterio.open(root / f"{sensor}.tif", "w", **profile) as dst:
            for index, role in enumerate(roles, 1):
                with rasterio.open(manifest.parent / f"{role}.tif") as src:
                    dst.write(src.read(1), index)
                dst.set_band_description(index, role)
                if sensor == "sar":
                    dst.set_band_unit(index, "linear")
            dst.update_tags(MODALITY=sensor, ACQUISITION_DATE="2026-01-01",
                            provenance="Synthetic software fixture, not satellite observations")
    (root / "expected.json").write_text(json.dumps({"synthetic_only": True,
        "reference_water_pixels": 128, "reference_builtup_pixels": 144,
        "note": "Manually defined reference rectangles. Default API filtering can change detection counts; these are not measured satellite accuracy."}, indent=2), encoding="utf-8")
    return root / "optical.tif", root / "sar.tif"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        optical, sar = create_pack(args.directory)
    except OSError as exc:
        parser.exit(2, f"Cannot create Pack C: {exc}\n")
    print(f"Upload {optical} and {sar}; ask for water and built-up regions using optical and SAR.")


if __name__ == "__main__":
    main()
