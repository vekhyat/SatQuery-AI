from __future__ import annotations

import argparse
import re
import struct
import sys
import zlib
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import numpy as np
import rasterio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from rasterio.enums import Resampling
from rasterio.errors import RasterioIOError

from apps.api.main import Settings, create_app
from satquery.contracts import AssetRecord, Modality
from satquery.errors import SatQueryError

STATIC_DIR = Path(__file__).resolve().parent / "dist"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5173
MAX_PREVIEW_EDGE = 768
MAX_SOURCE_PIXELS = 100_000_000
MAX_DECODE_BYTES = 64 * 1024 * 1024
PREVIEW_UNAVAILABLE_MESSAGE = (
    "Preview unavailable; validated file can still be queried."
)
_RGB_NAMES = {
    "red": frozenset({"red", "r", "b04", "b4", "band4", "band04"}),
    "green": frozenset({"green", "g", "grn", "b03", "b3", "band3", "band03"}),
    "blue": frozenset({"blue", "b", "blu", "b02", "b2", "band2", "band02"}),
}


def _preview_unavailable(cause: BaseException | None = None) -> SatQueryError:
    error = SatQueryError(422, "preview_unavailable", PREVIEW_UNAVAILABLE_MESSAGE)
    if cause is not None:
        error.__cause__ = cause
    return error


def _normalize_description(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _match_rgb_indexes(descriptions: list[str | None]) -> list[int] | None:
    normalized = [_normalize_description(item) for item in descriptions]
    used: set[int] = set()
    indexes: list[int] = []
    for channel in ("red", "green", "blue"):
        names = _RGB_NAMES[channel]
        match = next(
            (
                position
                for position, name in enumerate(normalized)
                if position not in used and name in names
            ),
            None,
        )
        if match is None:
            return None
        used.add(match)
        indexes.append(match + 1)
    return indexes


def _select_band_indexes(dataset: rasterio.DatasetReader, modality: Modality) -> list[int]:
    if modality in {Modality.SAR, Modality.UNKNOWN} or dataset.count < 3:
        return [1]
    rgb = _match_rgb_indexes(list(dataset.descriptions))
    if rgb is not None:
        return rgb
    return [1, 2, 3]


def _thumbnail_shape(width: int, height: int) -> tuple[int, int]:
    longest = max(width, height)
    if longest <= MAX_PREVIEW_EDGE:
        return width, height
    scale = MAX_PREVIEW_EDGE / longest
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _block_decode_bytes(dataset: rasterio.DatasetReader, indexes: list[int]) -> int:
    total = 0
    for index in indexes:
        block_height, block_width = dataset.block_shapes[index - 1]
        itemsize = int(np.dtype(dataset.dtypes[index - 1]).itemsize)
        total += int(block_height) * int(block_width) * itemsize
    return total


def _valid_mask(band: np.ndarray, nodata: float | None) -> np.ndarray:
    mask = np.isfinite(band)
    if nodata is not None and np.isfinite(nodata):
        mask &= band != nodata
    return mask


def _stretch_band(band: np.ndarray, valid: np.ndarray) -> np.ndarray:
    out = np.zeros(band.shape, dtype=np.uint8)
    if not np.any(valid):
        return out
    samples = np.asarray(band[valid], dtype=np.float64)
    low, high = np.percentile(samples, (2.0, 98.0))
    span = high - low
    if span == 0:
        out[valid] = 128
        return out
    scaled = (np.asarray(band, dtype=np.float64) - low) / span
    np.clip(scaled, 0.0, 1.0, out=scaled)
    stretched = np.rint(scaled * 255.0).astype(np.uint8)
    return np.where(valid, stretched, np.uint8(0))


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png_rgba(pixels: bytes, width: int, height: int) -> bytes:
    row_bytes = width * 4
    if len(pixels) != height * row_bytes:
        raise ValueError("RGBA buffer does not match the PNG dimensions.")
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        start = row * row_bytes
        raw.extend(pixels[start : start + row_bytes])
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6)),
            _png_chunk(b"IEND", b""),
        )
    )


def render_preview_png(path: Path, record: AssetRecord) -> bytes:
    try:
        with rasterio.open(path) as dataset:
            if dataset.driver != "GTiff":
                raise _preview_unavailable()
            width = int(dataset.width)
            height = int(dataset.height)
            if width < 1 or height < 1 or dataset.count < 1:
                raise _preview_unavailable()
            if width * height > MAX_SOURCE_PIXELS:
                raise _preview_unavailable()

            indexes = _select_band_indexes(dataset, record.metadata.modality)
            if any(index < 1 or index > dataset.count for index in indexes):
                raise _preview_unavailable()

            out_width, out_height = _thumbnail_shape(width, height)
            itemsize = max(int(np.dtype(dataset.dtypes[index - 1]).itemsize) for index in indexes)
            output_bytes = out_width * out_height * len(indexes) * itemsize
            if (
                _block_decode_bytes(dataset, indexes) > MAX_DECODE_BYTES
                or output_bytes > MAX_DECODE_BYTES
            ):
                raise _preview_unavailable()

            data = dataset.read(
                indexes,
                out_shape=(len(indexes), out_height, out_width),
                resampling=Resampling.nearest,
            )
            nodatavals = list(dataset.nodatavals)
            dataset_nodata = dataset.nodata
    except SatQueryError:
        raise
    except (OSError, RasterioIOError, ValueError, TypeError) as exc:
        raise _preview_unavailable(exc) from exc

    if data.ndim != 3 or data.shape[0] != len(indexes):
        raise _preview_unavailable()

    stretched: list[np.ndarray] = []
    valid_all = np.ones(data.shape[1:], dtype=bool)
    for band_offset, band in enumerate(data):
        nodata = nodatavals[indexes[band_offset] - 1] if indexes[band_offset] - 1 < len(nodatavals) else dataset_nodata
        valid = _valid_mask(np.asarray(band), nodata)
        valid_all &= valid
        stretched.append(_stretch_band(np.asarray(band), valid))

    gray_or_rgb = stretched[:3] if len(stretched) >= 3 else [stretched[0], stretched[0], stretched[0]]
    alpha = np.where(valid_all, np.uint8(255), np.uint8(0))
    rgba = np.ascontiguousarray(
        np.stack((*gray_or_rgb, alpha), axis=-1),
        dtype=np.uint8,
    )
    return encode_png_rgba(rgba.tobytes(), out_width, out_height)


def _install_preview_route(api: FastAPI) -> None:
    @api.get("/preview/{asset_id}")
    def preview(request: Request, asset_id: UUID) -> Response:
        store = request.app.state.store
        record = store.load(asset_id)
        path = store.source_path(record)
        try:
            png = render_preview_png(path, record)
        except SatQueryError:
            raise
        except Exception as exc:
            raise _preview_unavailable(exc) from exc
        return Response(
            content=png,
            media_type="image/png",
            headers={"Cache-Control": "private,max-age=300"},
        )


def create_web_app(
    settings: Settings | None = None,
    *,
    static_dir: Path | None = None,
) -> FastAPI:
    api = create_app(settings)
    _install_preview_route(api)
    static_root = (static_dir or STATIC_DIR).resolve()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with api.router.lifespan_context(api):
            yield

    web = FastAPI(
        title="SatQuery AI",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    web.state.api = api
    web.mount("/api", api)
    web.mount("/", StaticFiles(directory=static_root, html=True), name="static")
    return web


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="SatQuery AI local web server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    uvicorn.run(create_web_app(), host=DEFAULT_HOST, port=args.port)


if __name__ == "__main__":
    main()
