from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import UploadFile

from satquery.checker import CHECKER_VERSION, check_pack, inspect_raster
from satquery.composer import compose_answer
from satquery.contracts import (
    ModalityHint,
    Overlay,
    Receipt,
    ResultEnvelope,
    Task,
    TraceStep,
    UploadResponse,
)
from satquery.registry import execute_tool
from satquery.router import ROUTER_VERSION, route_query, router_trace
from satquery.storage import AssetStore


class SatQueryService:
    def __init__(self, store: AssetStore) -> None:
        self.store = store

    async def upload(
        self,
        file: UploadFile,
        modality: ModalityHint,
        acquisition_date: date | None,
    ) -> UploadResponse:
        self.store.cleanup_expired()
        pending = await self.store.write_upload(file)
        try:
            metadata, warnings = inspect_raster(
                pending.path,
                modality_hint=modality,
                acquisition_date_hint=acquisition_date,
            )
            record = self.store.finalize(pending, metadata, warnings)
        except Exception:
            self.store.discard(pending.asset_id)
            raise
        return UploadResponse.model_validate(record.model_dump(exclude={"stored_name"}))

    def query(self, asset_ids: list[UUID], question: str) -> ResultEnvelope:
        self.store.cleanup_expired()
        assets = [self.store.load(asset_id) for asset_id in asset_ids]
        asset_warnings = [
            f"Asset {asset.asset_id}: {warning}"
            for asset in assets
            for warning in asset.warnings
        ]
        pack = check_pack(assets)
        plan = route_query(assets, question, pack)
        trace = [*pack.trace, router_trace(plan)]
        base_tools = [CHECKER_VERSION, ROUTER_VERSION]

        if plan.task is Task.REJECT:
            return ResultEnvelope(
                task=Task.REJECT,
                tools=base_tools,
                parameters=plan.parameters,
                facts={},
                answer_text=plan.reason or "The request is unsupported.",
                confidence=0.0,
                warnings=[*asset_warnings, *pack.warnings, *plan.warnings],
                overlay=Overlay(),
                receipt=Receipt(
                    why_this_tool=plan.why,
                    rejected=True,
                    reason=plan.reason,
                    trace=trace,
                ),
            )

        ordered_by_id = {asset.asset_id: asset for asset in assets}
        ordered_assets = [ordered_by_id[asset_id] for asset_id in plan.ordered_asset_ids]
        tool_result = execute_tool(plan.tool or "", ordered_assets, plan)
        trace.append(
            TraceStep(
                stage="tool",
                status="stub",
                message=f"{plan.tool} returned a declared stub result.",
                details={"facts_returned": bool(tool_result.facts)},
            )
        )
        return ResultEnvelope(
            task=plan.task,
            tools=[*base_tools, plan.tool or ""],
            parameters=plan.parameters,
            facts=tool_result.facts,
            answer_text=compose_answer(plan, tool_result),
            confidence=tool_result.confidence,
            warnings=[
                *asset_warnings,
                *pack.warnings,
                *plan.warnings,
                *tool_result.warnings,
            ],
            overlay=tool_result.overlay,
            receipt=Receipt(
                why_this_tool=plan.why,
                rejected=False,
                reason=None,
                trace=trace,
            ),
        )
