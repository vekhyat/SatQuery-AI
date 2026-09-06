"""Optional local integration server. The team can mount create_app() in its API.

Only catalogued datasets are accepted. The demo is for localhost development;
the team's API owns authentication, authorization, uploads, and job persistence.
"""
import argparse
from dataclasses import asdict
import logging
from pathlib import Path
import re
from threading import BoundedSemaphore

from . import Config, __version__, optical_sar_v1, prepare_request
from .artifacts import resolve_artifact, to_web_result
from .contracts import rejection
from .inputs import DatasetError, read_json

logger = logging.getLogger(__name__)
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def load_catalog(path):
    """Read a trusted server-side mapping of dataset IDs to scene manifests."""
    path = Path(path).expanduser().resolve()
    raw = read_json(path)
    if not isinstance(raw, dict) or set(raw) != {"datasets"} or not isinstance(raw["datasets"], dict) or not raw["datasets"]:
        raise DatasetError("Catalog must contain a nonempty datasets object mapping IDs to manifests.")
    result = {}
    for key, value in raw["datasets"].items():
        if not ID_PATTERN.fullmatch(key) or not isinstance(value, str) or not value.strip():
            raise DatasetError("Catalog IDs must be 1-64 letters/digits/_/-; values must be manifest paths.")
        manifest = (path.parent / value).resolve()
        request = read_json(manifest)
        # Cache trusted selection/configuration; clients cannot substitute paths.
        sources, config = prepare_request(request, base_dir=manifest.parent)
        result[key] = {"bands": {role: {**asdict(spec), "path": str(spec.path)} for role, spec in sources.items()},
                       "parameters": asdict(config)}
    return result


def create_app(catalog_path, output_dir, *, artifact_base_url="/artifacts", max_pixels=16_000_000, max_concurrent=1):
    """Construct the optional FastAPI app. Does not start a server on import.

The pixel limit is enforced on every source by the pipeline; client parameters
cannot increase this server ceiling. CPU jobs use FastAPI's sync thread pool.
"""
    try:
        from fastapi import FastAPI, Request
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import FileResponse, JSONResponse
    except ImportError as exc:
        raise RuntimeError('Install the API extra: python -m pip install ".[api]"') from exc
    if type(max_concurrent) is not int or max_concurrent < 1:
        raise DatasetError("max_concurrent must be a positive integer.")
    Config(max_pixels=max_pixels)
    catalog = load_catalog(catalog_path)
    output_dir = Path(output_dir).expanduser().resolve()
    slots = BoundedSemaphore(max_concurrent)
    app = FastAPI(title="SatQuery Tool 3 local integration", version=__version__)

    def reject(reason, code="invalid_request", status=422):
        return JSONResponse(rejection(reason, code), status_code=status)

    @app.exception_handler(RequestValidationError)
    async def invalid_body(request: Request, exc: RequestValidationError):
        return reject("Request must be a JSON object with dataset_id and optional parameters.")

    @app.get("/health")
    def health():
        return {"status": "ok", "tool": "optical_sar_v1", "version": __version__, "contract_version": "1.0"}

    @app.post("/tools/optical_sar_v1")
    def run(body: dict):
        if set(body) - {"dataset_id", "parameters"}:
            return reject("Use dataset_id and optional parameters only; paths and tool names are selected by the server.")
        dataset_id = body.get("dataset_id")
        if not isinstance(dataset_id, str) or dataset_id not in catalog:
            return reject("Unknown dataset_id.", "unknown_dataset", 404)
        overrides = body.get("parameters", {})
        if not isinstance(overrides, dict):
            return reject("parameters must be a JSON object.")
        saved = catalog[dataset_id]
        request = {"bands": saved["bands"], "parameters": {**saved["parameters"], **overrides}}
        try:
            _, config = prepare_request(request, base_dir=Path.cwd())
        except DatasetError:
            return reject("Invalid processing parameters; see the Tool 3 request schema.")
        if "max_pixels" in overrides and config.max_pixels > max_pixels:
            return reject("max_pixels exceeds the server limit.", "resource_limit")
        request["parameters"]["max_pixels"] = min(config.max_pixels, max_pixels)
        if not slots.acquire(blocking=False):
            response = reject("Tool 3 is busy; retry later.", "busy", 429)
            response.headers["Retry-After"] = "5"
            return response
        try:
            result = optical_sar_v1(request, base_dir=Path.cwd(), output_dir=output_dir)
            if result["task"] == "reject":
                logger.warning("Tool 3 dataset %s rejected: %s", dataset_id, result["receipt"]["reason"])
                return JSONResponse(to_web_result(result, output_dir=output_dir), status_code=422)
            return to_web_result(result, output_dir=output_dir, artifact_base_url=artifact_base_url)
        except Exception:
            logger.exception("Unexpected Tool 3 failure for dataset %s", dataset_id)
            return reject("Tool 3 failed; check the server log.", "internal_error", 500)
        finally:
            slots.release()

    @app.get("/artifacts/{run_id}/{filename}")
    def artifact(run_id: str, filename: str):
        try:
            path = resolve_artifact(output_dir, run_id, filename)
        except (DatasetError, OSError):
            return reject("Unknown artifact.", "unknown_artifact", 404)
        mime = "image/png" if path.suffix == ".png" else "image/tiff"
        return FileResponse(path, media_type=mime, headers={"X-Content-Type-Options": "nosniff"})

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "output")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--max-pixels", type=int, default=16_000_000)
    args = parser.parse_args(argv)
    try:
        import uvicorn
        app = create_app(args.catalog, args.output_dir, max_pixels=args.max_pixels)
    except (ImportError, RuntimeError, DatasetError) as exc:
        parser.exit(2, str(exc) + '\nInstall API dependencies with: python -m pip install ".[api]"\n')
    # Local demo: external hosting and access controls belong to the team API.
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
