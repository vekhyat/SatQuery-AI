from __future__ import annotations

import re

from satquery.checker import PackCheck
from satquery.contracts import AssetRecord, Modality, RoutePlan, Task, TraceStep

ROUTER_VERSION = "router_v1"

CHANGE_TERMS = {
    "after",
    "before",
    "change",
    "changed",
    "decrease",
    "decreased",
    "difference",
    "disappeared",
    "increase",
    "increased",
    "new",
    "temporal",
}
OPTICAL_SAR_COMPARISON_TERMS = {
    "cross-sensor",
    "fuse",
    "fusion",
    "modality",
    "multimodal",
}


def _question_intents(question: str) -> tuple[bool, bool]:
    tokens = set(re.findall(r"[a-z0-9]+", question.lower()))
    mentions_optical = "optical" in tokens
    mentions_sar = bool(tokens & {"radar", "sar"})
    asks_sensor_comparison = (
        bool(tokens & OPTICAL_SAR_COMPARISON_TERMS)
        or (mentions_optical and mentions_sar)
        or (
            "sensor" in tokens
            and bool(tokens & {"compare", "comparison", "cross"})
        )
    )
    return bool(tokens & CHANGE_TERMS), asks_sensor_comparison


def _reject(assets: list[AssetRecord], reason: str, code: str) -> RoutePlan:
    return RoutePlan(
        task=Task.REJECT,
        tool=None,
        ordered_asset_ids=[asset.asset_id for asset in assets],
        parameters={"rejection_code": code},
        why="The input and question do not form a supported specialist workflow.",
        rejected=True,
        reason=reason,
    )


def route_query(assets: list[AssetRecord], question: str, pack: PackCheck) -> RoutePlan:
    if not pack.ok:
        return _reject(assets, pack.reason or "The input pack is incompatible.", pack.code or "invalid_pack")

    asks_change, asks_optical_sar = _question_intents(question)
    modalities = [asset.metadata.modality for asset in assets]
    if Modality.UNKNOWN in modalities:
        return _reject(
            assets,
            "At least one file has unknown modality; re-upload it with optical or sar supplied.",
            "modality_required",
        )

    if len(assets) == 1:
        if asks_change:
            return _reject(
                assets,
                "A temporal-change question requires two aligned optical images from different dates.",
                "question_input_mismatch",
            )
        if asks_optical_sar:
            return _reject(
                assets,
                "An optical-SAR comparison requires one optical image and one SAR image.",
                "question_input_mismatch",
            )
        asset = assets[0]
        return RoutePlan(
            task=Task.SINGLE_IMAGE,
            tool="single_image_stub_v0",
            ordered_asset_ids=[asset.asset_id],
            parameters={"asset_id": str(asset.asset_id)},
            why="One valid GeoTIFF matches the single-image workflow.",
        )

    optical_assets = [asset for asset in assets if asset.metadata.modality is Modality.OPTICAL]
    sar_assets = [asset for asset in assets if asset.metadata.modality is Modality.SAR]

    if len(optical_assets) == 1 and len(sar_assets) == 1:
        if asks_change and not asks_optical_sar:
            return _reject(
                assets,
                "Temporal change currently requires two optical images, not an optical-SAR pair.",
                "question_input_mismatch",
            )
        optical = optical_assets[0]
        sar = sar_assets[0]
        return RoutePlan(
            task=Task.OPTICAL_SAR,
            tool="optical_sar_v1",
            ordered_asset_ids=[optical.asset_id, sar.asset_id],
            parameters={
                "optical_asset_id": str(optical.asset_id),
                "sar_asset_id": str(sar.asset_id),
            },
            why="The exact-grid pair contains one optical and one SAR GeoTIFF.",
        )

    if len(optical_assets) == 2:
        if asks_optical_sar:
            return _reject(
                assets,
                "An optical-SAR question requires one of the two files to be SAR.",
                "question_input_mismatch",
            )
        if any(asset.metadata.acquisition_date is None for asset in optical_assets):
            return _reject(
                assets,
                "Both optical images need acquisition dates for temporal routing.",
                "acquisition_date_required",
            )
        ordered = sorted(
            optical_assets,
            key=lambda asset: asset.metadata.acquisition_date,
        )
        before_date = ordered[0].metadata.acquisition_date
        after_date = ordered[1].metadata.acquisition_date
        if before_date == after_date:
            return _reject(
                assets,
                "Temporal change requires optical images from two different dates.",
                "different_dates_required",
            )
        return RoutePlan(
            task=Task.CHANGE,
            tool="change_stub_v0",
            ordered_asset_ids=[asset.asset_id for asset in ordered],
            parameters={
                "before_asset_id": str(ordered[0].asset_id),
                "after_asset_id": str(ordered[1].asset_id),
                "before_date": before_date.isoformat(),
                "after_date": after_date.isoformat(),
            },
            why="Two exact-grid optical GeoTIFFs from different dates match the change workflow.",
        )

    return _reject(
        assets,
        "This two-file modality combination is not supported by the current specialists.",
        "unsupported_modality_combination",
    )


def router_trace(plan: RoutePlan) -> TraceStep:
    return TraceStep(
        stage="router",
        status="rejected" if plan.rejected else "ok",
        message=plan.reason if plan.rejected else plan.why,
        details={"task": plan.task.value, "tool": plan.tool},
    )
