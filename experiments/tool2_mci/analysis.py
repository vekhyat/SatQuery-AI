"""Pure post-processing for semantic change masks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np


CLASS_DEFINITIONS = {
    "unchanged_background": {"class_id": 0, "label": "unchanged/background"},
    "road_change": {"class_id": 1, "label": "road change"},
    "building_change": {"class_id": 2, "label": "building change"},
}
GEOSPATIAL_WARNING = (
    "Physical change area is unavailable because the input does not contain a "
    "validated geospatial transform/pixel resolution."
)


def _validate_mask(mask: np.ndarray) -> np.ndarray:
    array = np.asarray(mask)
    if array.ndim != 2:
        raise ValueError(f"Expected a 2-D semantic mask, got shape {array.shape}")
    if not np.all(np.isin(array, (0, 1, 2))):
        raise ValueError("Semantic mask must contain only classes 0, 1, and 2")
    return array.astype(np.uint8, copy=False)


def _percent(numerator: int, denominator: int) -> float:
    return numerator * 100.0 / denominator if denominator else 0.0


def compute_change_statistics(
    mask: np.ndarray,
    valid_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    semantic = _validate_mask(mask)
    if valid_mask is None:
        valid = np.ones(semantic.shape, dtype=bool)
    else:
        valid = np.asarray(valid_mask, dtype=bool)
        if valid.shape != semantic.shape:
            raise ValueError("valid_mask must have the same shape as the semantic mask")

    total_pixels = int(semantic.size)
    valid_pixels = int(np.count_nonzero(valid))
    counts = {
        class_id: int(np.count_nonzero((semantic == class_id) & valid))
        for class_id in range(3)
    }
    changed_pixels = counts[1] + counts[2]

    classes: dict[str, dict[str, Any]] = {}
    for name, definition in CLASS_DEFINITIONS.items():
        class_id = definition["class_id"]
        class_stats = {
            **definition,
            "pixel_count": counts[class_id],
            "percent_of_valid_pixels": _percent(counts[class_id], valid_pixels),
        }
        if class_id in (1, 2):
            class_stats["percent_of_changed_pixels"] = _percent(
                counts[class_id], changed_pixels
            )
        classes[name] = class_stats

    if sum(item["pixel_count"] for item in classes.values()) != valid_pixels:
        raise RuntimeError("Class pixel counts do not sum to valid_pixels")
    if classes["road_change"]["pixel_count"] + classes["building_change"][
        "pixel_count"
    ] != changed_pixels:
        raise RuntimeError("Changed class counts do not sum to changed_pixels")

    return {
        "total_pixels": total_pixels,
        "valid_pixels": valid_pixels,
        "unchanged_pixels": counts[0],
        "changed_pixels": changed_pixels,
        "changed_fraction": changed_pixels / valid_pixels if valid_pixels else 0.0,
        "changed_percent": _percent(changed_pixels, valid_pixels),
        "classes": classes,
    }


def _connected_components(binary: np.ndarray, connectivity: int) -> list[list[tuple[int, int]]]:
    if connectivity not in (4, 8):
        raise ValueError("connectivity must be 4 or 8")
    if connectivity == 4:
        offsets = ((-1, 0), (0, -1), (0, 1), (1, 0))
    else:
        offsets = tuple(
            (dy, dx)
            for dy in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if (dy, dx) != (0, 0)
        )

    height, width = binary.shape
    visited = np.zeros(binary.shape, dtype=bool)
    components: list[list[tuple[int, int]]] = []
    for y in range(height):
        for x in range(width):
            if not binary[y, x] or visited[y, x]:
                continue
            visited[y, x] = True
            stack = [(y, x)]
            pixels: list[tuple[int, int]] = []
            while stack:
                current_y, current_x = stack.pop()
                pixels.append((current_y, current_x))
                for delta_y, delta_x in offsets:
                    neighbor_y = current_y + delta_y
                    neighbor_x = current_x + delta_x
                    if (
                        0 <= neighbor_y < height
                        and 0 <= neighbor_x < width
                        and binary[neighbor_y, neighbor_x]
                        and not visited[neighbor_y, neighbor_x]
                    ):
                        visited[neighbor_y, neighbor_x] = True
                        stack.append((neighbor_y, neighbor_x))
            components.append(pixels)
    return components


def _component_group(
    binary: np.ndarray,
    class_name: str,
    class_id: int | None,
    min_pixels: int,
    connectivity: int,
    total_changed_pixels: int,
) -> dict[str, Any]:
    raw_components = _connected_components(binary, connectivity)
    group_pixels = int(np.count_nonzero(binary))
    items = []
    for raw_component_id, pixels in enumerate(raw_components, start=1):
        pixel_area = len(pixels)
        if pixel_area < min_pixels:
            continue
        rows = np.asarray([pixel[0] for pixel in pixels], dtype=np.int64)
        columns = np.asarray([pixel[1] for pixel in pixels], dtype=np.int64)
        items.append(
            {
                "component_id": raw_component_id,
                "class": class_name,
                "class_id": class_id,
                "pixel_area": pixel_area,
                "bounding_box_pixels": {
                    "x_min": int(columns.min()),
                    "y_min": int(rows.min()),
                    "x_max_exclusive": int(columns.max()) + 1,
                    "y_max_exclusive": int(rows.max()) + 1,
                },
                "centroid_pixels": {
                    "x": float(columns.mean()),
                    "y": float(rows.mean()),
                },
                "percent_of_total_changed_pixels": _percent(
                    pixel_area, total_changed_pixels
                ),
            }
        )

    items.sort(key=lambda item: (-item["pixel_area"], item["component_id"]))
    filtered_pixels = sum(item["pixel_area"] for item in items)
    largest = items[0]["pixel_area"] if items else None
    return {
        "raw_component_count": len(raw_components),
        "filtered_component_count": len(items),
        "filtered_pixel_count": filtered_pixels,
        "filtered_components_percent_of_group_pixels": _percent(
            filtered_pixels, group_pixels
        ),
        "largest_component_pixels": largest,
        "largest_component_percent_of_group_pixels": (
            _percent(largest, group_pixels) if largest is not None else None
        ),
        "items": items,
    }


def extract_change_components(
    mask: np.ndarray,
    min_pixels: int = 6,
    connectivity: int = 8,
) -> dict[str, Any]:
    semantic = _validate_mask(mask)
    if min_pixels < 1:
        raise ValueError("min_pixels must be at least 1")
    if connectivity not in (4, 8):
        raise ValueError("connectivity must be 4 or 8")
    total_changed = int(np.count_nonzero(semantic))
    return {
        "minimum_component_pixels": int(min_pixels),
        "connectivity": connectivity,
        "all_changed": _component_group(
            semantic != 0,
            "all_changed",
            None,
            min_pixels,
            connectivity,
            total_changed,
        ),
        "road_change": _component_group(
            semantic == 1,
            "road_change",
            1,
            min_pixels,
            connectivity,
            total_changed,
        ),
        "building_change": _component_group(
            semantic == 2,
            "building_change",
            2,
            min_pixels,
            connectivity,
            total_changed,
        ),
    }


def physical_area_from_metadata(
    changed_pixels: int,
    metadata: Mapping[str, Any] | None,
) -> tuple[dict[str, float | None], str | None]:
    unavailable = {
        "physical_area_m2": None,
        "physical_area_hectares": None,
        "coordinates": None,
    }
    if not metadata:
        return unavailable, GEOSPATIAL_WARNING

    metric_units = {"m", "meter", "meters", "metre", "metres"}
    required = (
        metadata.get("validated") is True,
        bool(metadata.get("crs")),
        metadata.get("is_projected") is True,
        str(metadata.get("linear_units", "")).lower() in metric_units,
    )
    try:
        pixel_width = float(metadata["pixel_width"])
        pixel_height = float(metadata["pixel_height"])
        dimensions_valid = (
            np.isfinite(pixel_width)
            and np.isfinite(pixel_height)
            and pixel_width != 0
            and pixel_height != 0
        )
    except (KeyError, TypeError, ValueError):
        dimensions_valid = False
        pixel_width = pixel_height = 0.0
    if not all(required) or not dimensions_valid:
        return unavailable, GEOSPATIAL_WARNING

    area_m2 = float(changed_pixels) * abs(pixel_width * pixel_height)
    return {
        "physical_area_m2": area_m2,
        "physical_area_hectares": area_m2 / 10_000.0,
        "coordinates": None,
    }, None
