"""Portable PNG/GeoTIFF/JSON artifacts and a local HTML viewer."""
from html import escape
import json
from pathlib import Path
import numpy as np
from PIL import Image
import rasterio

PALETTE = {0: (62, 78, 91, 255), 1: (39, 164, 242, 255),
           2: (248, 107, 89, 255), 255: (0, 0, 0, 0)}


def save_png(path, array):
    Image.fromarray(array).save(path)


def class_rgba(classes):
    lut = np.zeros((256, 4), dtype=np.uint8)
    for code, color in PALETTE.items():
        lut[code] = color
    return lut[classes]


def stretch(data):
    valid = np.isfinite(data)
    output = np.zeros(data.shape, dtype=np.uint8)
    if valid.any():
        low, high = np.percentile(data[valid], [2, 98])
        if high > low:
            output[valid] = (np.clip((data[valid] - low) / (high - low), 0, 1) * 255).astype(np.uint8)
        else:
            output[valid] = 128
    return output


def save_tif(path, array, grid, nodata, description, classmap=False):
    with rasterio.open(path, "w", driver="GTiff", width=grid["width"], height=grid["height"],
                       count=1, dtype=array.dtype, crs=grid["crs"], transform=grid["transform"],
                       nodata=nodata, compress="deflate") as destination:
        destination.write(array, 1)
        destination.set_band_description(1, description)
        destination.update_tags(method="Tool 3 threshold baseline; candidate regions, not validated labels")
        if classmap:
            destination.write_colormap(1, PALETTE)
            destination.update_tags(classes="0=other;1=water_candidate;2=builtup_candidate;255=nodata")


def write_outputs(stage, result, maps, masks, grid, indices, bands, sar_db):
    for name, value in maps.items():
        save_png(stage / f"{name}.png", class_rgba(value))
        save_tif(stage / f"{name}.tif", value, grid, 255, name, classmap=True)
    for name, (mask, valid) in masks.items():
        rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
        rgba[:, :, :3] = (mask[:, :, None] * 255).astype(np.uint8)
        rgba[:, :, 3] = (valid * 255).astype(np.uint8)
        save_png(stage / f"{name}.png", rgba)
        value = mask.astype(np.uint8)
        value[~valid] = 255
        save_tif(stage / f"{name}.tif", value, grid, 255, "0=negative;1=positive;255=nodata")
    for name, value in {**indices, **{f"sar_{k}_db": v for k, v in sar_db.items()}}.items():
        value = np.where(np.isfinite(value), value, -9999).astype(np.float32)
        save_tif(stage / f"{name}.tif", value, grid, -9999, name)
    rgb_roles = ("red", "green", "blue") if {"red", "blue"} <= bands.keys() else ("swir", "nir", "green")
    rgb = np.stack([stretch(bands[role]) for role in rgb_roles], axis=-1)
    alpha = np.logical_and.reduce([np.isfinite(bands[role]) for role in rgb_roles]).astype(np.uint8) * 255
    save_png(stage / "optical_preview.png", np.dstack([rgb, alpha]))
    sar = stretch(sar_db["vv"])
    save_png(stage / "sar_preview.png", np.dstack([sar, sar, sar, np.isfinite(sar_db["vv"]).astype(np.uint8) * 255]))
    result["facts"]["optical_preview_bands"] = list(rgb_roles)
    result["receipt"]["artifacts"] = sorted(p.name for p in stage.iterdir()) + ["result.json", "report.html"]
    (stage / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    (stage / "report.html").write_text(render_report(result), encoding="utf-8")


def render_report(result):
    facts = result["facts"]
    warnings = "".join(f"<li>{escape(w)}</li>" for w in result["warnings"])
    rows = []
    for layer, data in facts["layers"].items():
        rows.append(f"<tr><th>{escape(layer.replace('_', ' ').title())}</th><td>{data['valid_pixels']:,}</td>"
                    f"<td>{data['water']['pixels']:,}</td><td>{data['builtup']['pixels']:,}</td></tr>")
    payload = json.dumps(facts, allow_nan=False).replace("<", "\\u003c")
    dates = facts["dates"]
    grid = result["receipt"]["reference_grid"]
    template = (Path(__file__).parent / "report_template.html").read_text(encoding="utf-8")
    replacements = {
        "OPTDATE": dates["optical"] or "unknown", "SARDATE": dates["sar"] or "unknown", "CRS": grid["crs"],
        "DIMENSIONS": f"{grid['width']} × {grid['height']}",
        "WATER": f"{facts['layers']['fused']['water']['pixels']:,}", "BUILT": f"{facts['layers']['fused']['builtup']['pixels']:,}",
        "CHANGED": f"{facts['changed_from_optical_pixels']:,}", "CONTRIBUTION": facts["sar_contribution"],
        "RUNID": result["receipt"]["run_id"], "CHANNELS": ", ".join(facts["optical_preview_bands"]),
    }
    for key, value in replacements.items():
        template = template.replace(f"__{key}__", escape(str(value)))
    return template.replace("__ROWS__", "".join(rows)).replace("__WARNINGS__", warnings).replace("__FACTS__", payload)
