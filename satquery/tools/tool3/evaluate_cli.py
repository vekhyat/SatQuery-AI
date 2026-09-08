"""Compare one candidate GeoTIFF to a independently labelled reference GeoTIFF."""
import argparse
import json
from pathlib import Path
import sys
import rasterio
from satquery.tools.tool3 import DatasetError
from satquery.tools.tool3.evaluation import evaluate_files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--reference-nodata", type=float)
    parser.add_argument("--max-pixels", type=int, default=16_000_000)
    parser.add_argument("--output", type=Path, help="Optional new JSON file; existing files are not overwritten.")
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.exists():
            raise DatasetError(f"Output already exists: {args.output}. Choose a new evaluation filename.")
        result = evaluate_files(args.prediction, args.reference, args.reference_nodata, args.max_pixels)
        text = json.dumps(result, indent=2, allow_nan=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(text)
        print(text)
        return 0
    except (DatasetError, OSError, rasterio.errors.RasterioError, MemoryError) as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc) or "Insufficient memory; crop the inputs."}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
