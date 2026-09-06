"""Command-line entry point. Failures use the same envelope as successful runs."""
import argparse
from dataclasses import fields
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import re
import uuid
import webbrowser
import rasterio
from .inputs import DatasetError, discover, load_manifest, read_json
from .pipeline import Config, check_dataset, run_pipeline
from .contracts import rejection
from ._version import __version__

# Source checkout retains its existing no-argument workflow. Installed wheels
# use the caller's directory, never attempt writes beneath site-packages.
_SOURCE_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = _SOURCE_ROOT if (_SOURCE_ROOT / "tool3.py").is_file() else Path.cwd()


def parser():
    p = argparse.ArgumentParser(description="Tool 3: align optical/SAR rasters and identify water/built-up candidates.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--optical-dir", type=Path)
    p.add_argument("--sar-dir", type=Path)
    source = p.add_mutually_exclusive_group()
    source.add_argument("--manifest", type=Path, help="JSON with explicit band paths/indexes and optional parameters.")
    source.add_argument("--batch", type=Path, help="JSON listing named dataset manifests; continue after individual failures.")
    p.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "output", help="Parent for unique, complete run folders.")
    p.add_argument("--sar-units", choices=["auto", "linear", "db"], default=None)
    for name in ("ndwi_threshold", "ndbi_threshold", "vegetation_threshold", "sar_water_vv_db", "sar_water_vh_db",
                 "sar_built_vv_db", "sar_built_vh_db", "min_component_m2", "min_overlap"):
        p.add_argument("--" + name.replace("_", "-"), type=float, default=None)
    for name in ("speckle_size", "morphology_size", "min_component_pixels", "max_date_gap_days", "max_pixels"):
        p.add_argument("--" + name.replace("_", "-"), type=int, default=None)
    p.add_argument("--json", action="store_true", help="Write only result JSON to stdout, including rejections.")
    p.add_argument("--open-report", action="store_true", help="Open the finished report in your default browser.")
    p.add_argument("--check-only", action="store_true", help="Validate headers, units, and geographic intersection without reading pixels or writing output.")
    return p


def selected_config(parameters, args):
    allowed = {field.name for field in fields(Config)}
    if set(parameters) - allowed:
        raise DatasetError("Unknown parameters: " + ", ".join(sorted(set(parameters) - allowed)))
    parameters = dict(parameters)
    parameters.update({name: getattr(args, name) for name in allowed if getattr(args, name) is not None})
    return Config(**parameters)


def run_batch(args):
    path = args.batch.expanduser().resolve()
    batch = read_json(path)
    if not isinstance(batch, dict) or set(batch) != {"datasets"} or not isinstance(batch["datasets"], list) or not batch["datasets"]:
        raise DatasetError("Batch JSON must contain a nonempty 'datasets' list of {name, manifest} objects.")
    seen = set()
    for item in batch["datasets"]:
        if not isinstance(item, dict) or set(item) != {"name", "manifest"}:
            raise DatasetError("Each batch item must contain name and manifest only.")
        name = item["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name):
            raise DatasetError("Batch names must be 1-64 letters/digits/underscores/hyphens, starting with a letter/digit.")
        if name.casefold() in seen:
            raise DatasetError(f"Duplicate batch name: {name}")
        seen.add(name.casefold())
        if not isinstance(item["manifest"], str) or not item["manifest"].strip():
            raise DatasetError(f"{name}: manifest must be a nonempty path.")
    results = []
    for item in batch["datasets"]:
        try:
            sources, parameters = load_manifest(path.parent / item["manifest"])
            config = selected_config(parameters, args)
            outcome = check_dataset(sources, config) if args.check_only else run_pipeline(sources, args.output_dir / item["name"], config)
            results.append({"name": item["name"], "status": "checked" if args.check_only else "completed", "result": outcome})
        except (DatasetError, OSError, rasterio.errors.RasterioError, MemoryError) as exc:
            reason = "Insufficient memory; crop the scene or lower its resolution before processing." if isinstance(exc, MemoryError) else str(exc)
            results.append({"name": item["name"], "status": "rejected", "result": rejection(reason)})
    failed = sum(item["status"] == "rejected" for item in results)
    summary = {"task": "batch", "check_only": args.check_only, "datasets": results,
               "succeeded": len(results) - failed, "failed": failed}
    if not args.check_only:
        parent = args.output_dir.expanduser().resolve() / "batches"
        parent.mkdir(parents=True, exist_ok=True)
        name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
        destination = parent / f"{name}.json"
        summary["summary_file"] = str(destination)
        temporary = parent / f".{name}.tmp"
        temporary.write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(destination)
    return summary


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if (args.manifest or args.batch) and (args.optical_dir or args.sar_dir):
            raise DatasetError("Choose a manifest/batch or input folders; do not specify both.")
        if args.open_report and (args.check_only or args.batch):
            raise DatasetError("--open-report is available for a single completed run, not --check-only or --batch.")
        if args.batch:
            result = run_batch(args)
            if args.json:
                print(json.dumps(result, indent=2, allow_nan=False))
            else:
                print(f"Batch: {result['succeeded']} succeeded, {result['failed']} rejected.")
                for item in result["datasets"]:
                    message = item["result"]["receipt"]["reason"] if item["status"] == "rejected" else item["status"]
                    print(f"  {item['name']}: {message}")
                if "summary_file" in result:
                    print("Batch summary:", result["summary_file"])
            return 2 if result["failed"] else 0
        if args.manifest:
            sources, parameters = load_manifest(args.manifest)
        else:
            sources, parameters = discover(args.optical_dir or PROJECT_ROOT / "optical" / "optical_images",
                                           args.sar_dir or PROJECT_ROOT / "sar" / "sar_images"), {}
        config = selected_config(parameters, args)
        if args.check_only:
            result = check_dataset(sources, config)
            print(json.dumps(result, indent=2, allow_nan=False) if args.json else
                  f"Metadata checks passed for {len(sources)} bands. Pixel validity/overlap and accuracy are not checked; run without --check-only to generate maps.")
            return 0
        result = run_pipeline(sources, args.output_dir, config)
    except (DatasetError, OSError, rasterio.errors.RasterioError, MemoryError) as exc:
        reason = "Insufficient memory; crop the scene or lower its resolution before processing." if isinstance(exc, MemoryError) else str(exc)
        result = rejection(reason)
        print(json.dumps(result, indent=2, allow_nan=False) if args.json else "Cannot run Tool 3: " + reason,
              file=sys.stdout if args.json else sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, allow_nan=False))
    else:
        print(result["answer_text"])
        print("Report:", Path(result["receipt"]["output_dir"]) / "report.html")
        print("Result:", Path(result["receipt"]["output_dir"]) / "result.json")
        print(f"Validation notes: {len(result['warnings'])}; see report/JSON. Confidence is not calibrated.")
    if args.open_report:
        webbrowser.open((Path(result["receipt"]["output_dir"]) / "report.html").as_uri())
    return 0
