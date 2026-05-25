from __future__ import annotations

import asyncio
from datetime import datetime

from kb_pipeline.clients.auth import Class101AuthClient
from kb_pipeline.clients.docbuilder import DocBuilderClient
from kb_pipeline.clients.llm import LLMClient
from kb_pipeline.clients.nocodb import NocoDBClient
from kb_pipeline.clients.ocr import OCRClient
from kb_pipeline.clients.slack import SlackClient
from kb_pipeline.clients.terms import TermsClient
from kb_pipeline.config import COLLECTION_CUTOFF
from kb_pipeline.merge import decide_merge
from kb_pipeline.models import (
    PipelineMode,
    PipelineResult,
    PipelineRuntime,
    PipelineScope,
    TriggerType,
    WriteMode,
)
from kb_pipeline.pipelines.docbuilder_pipeline import DocBuilderPipeline
from kb_pipeline.pipelines.event_pipeline import EventPipeline
from kb_pipeline.pipelines.slack_pipeline import SlackPipeline
from kb_pipeline.pipelines.terms_pipeline import TermsPipeline
from kb_pipeline.settings import get_settings
from kb_pipeline.state import PipelineStateStore


class PipelineRunner:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.state = PipelineStateStore(self.settings.state_db)

    def run(
        self,
        *,
        mode: PipelineMode,
        trigger_type: TriggerType = TriggerType.MANUAL,
        write_mode: WriteMode = "dry-run",
        target_sources: list[str] | None = None,
        limit: int | None = None,
        lookback_hours: int | None = None,
        scope: PipelineScope | None = None,
    ) -> PipelineResult:
        return asyncio.run(
            self.run_async(
                mode=mode,
                trigger_type=trigger_type,
                write_mode=write_mode,
                target_sources=target_sources,
                limit=limit,
                lookback_hours=lookback_hours,
                scope=scope,
            )
        )

    async def run_async(
        self,
        *,
        mode: PipelineMode,
        trigger_type: TriggerType = TriggerType.MANUAL,
        write_mode: WriteMode = "dry-run",
        target_sources: list[str] | None = None,
        limit: int | None = None,
        lookback_hours: int | None = None,
        scope: PipelineScope | None = None,
    ) -> PipelineResult:
        runtime = PipelineRuntime(
            mode=mode,
            trigger_type=trigger_type,
            write_mode=write_mode,
            target_sources=target_sources or ["slack", "event", "docbuilder", "terms"],
            limit=limit,
            lookback_hours=lookback_hours or 6,
            scope=scope,
        )
        now = datetime.now(tz=COLLECTION_CUTOFF.tzinfo)
        noco = NocoDBClient(
            base_url=self.settings.noco_base_url,
            token=self.settings.noco_api_token,
        )
        records = await self._collect_records(runtime, noco=noco)
        summary = await self._process_records(runtime=runtime, records=records, noco=noco)
        result = PipelineResult(
            mode=runtime.mode,
            trigger_type=runtime.trigger_type,
            write_mode=runtime.write_mode,
            scope=runtime.scope,
            summary=summary,
            records=records,
            errors=summary.pop("_errors", []),
        )
        self.state.insert_run_log(
            mode=f"{runtime.trigger_type.value}:{runtime.mode.value}",
            write_mode=runtime.write_mode,
            summary=result.summary,
            created_at=now.isoformat(),
        )
        return result

    async def _collect_records(self, runtime: PipelineRuntime, *, noco: NocoDBClient):
        llm = LLMClient(
            api_key=self.settings.openai_api_key,
            model=self.settings.openai_model,
        )
        needs_admin = bool({"event", "docbuilder"} & set(runtime.target_sources))
        admin_authorization = await self._admin_authorization() if needs_admin else None
        records = []
        if "slack" in runtime.target_sources:
            records.extend(
                await SlackPipeline(
                    slack=SlackClient(self.settings.slack_bot_token),
                    llm=llm,
                ).collect(
                    mode=runtime.mode,
                    limit=runtime.limit,
                    use_fixtures_when_unconfigured=runtime.use_fixtures_when_unconfigured,
                    scope=runtime.scope,
                    trigger_type=runtime.trigger_type.value,
                    lookback_hours=runtime.lookback_hours,
                )
            )
        if "event" in runtime.target_sources:
            records.extend(
                await EventPipeline(
                    docbuilder=DocBuilderClient(
                        graphql_url=self.settings.class101_admin_graphql_url,
                        authorization=admin_authorization,
                        noco_base_url=self.settings.noco_base_url,
                        noco_token=self.settings.noco_api_token,
                    ),
                    ocr=OCRClient(base_url=self.settings.ocr_base_url),
                    llm=llm,
                    noco=noco,
                ).collect(
                    mode=runtime.mode,
                    limit=runtime.limit,
                    use_fixtures_when_unconfigured=runtime.use_fixtures_when_unconfigured,
                )
            )
        if "docbuilder" in runtime.target_sources:
            records.extend(
                await DocBuilderPipeline(
                    docbuilder=DocBuilderClient(
                        graphql_url=self.settings.class101_admin_graphql_url,
                        authorization=admin_authorization,
                        noco_base_url=self.settings.noco_base_url,
                        noco_token=self.settings.noco_api_token,
                    ),
                    ocr=OCRClient(base_url=self.settings.ocr_base_url),
                    llm=llm,
                    noco=noco,
                    state=self.state,
                ).collect(
                    mode=runtime.mode,
                    limit=runtime.limit,
                    use_fixtures_when_unconfigured=runtime.use_fixtures_when_unconfigured,
                )
            )
        if "terms" in runtime.target_sources:
            records.extend(
                await TermsPipeline(
                    terms=TermsClient(),
                    llm=llm,
                    noco=noco,
                ).collect(
                    mode=runtime.mode,
                    limit=runtime.limit,
                    use_fixtures_when_unconfigured=runtime.use_fixtures_when_unconfigured,
                )
            )
        return records

    async def _admin_authorization(self) -> str | None:
        if self.settings.class101_admin_authorization:
            return self.settings.class101_admin_authorization
        return await Class101AuthClient(
            firebase_token_url=self.settings.class101_firebase_token_url,
            refresh_token=self.settings.class101_refresh_token,
        ).admin_authorization()

    async def _process_records(
        self,
        *,
        runtime: PipelineRuntime,
        records,
        noco: NocoDBClient,
    ) -> dict:
        summary = {
            "target_sources": runtime.target_sources,
            "trigger_type": runtime.trigger_type.value,
            "scope": runtime.scope.model_dump() if runtime.scope else None,
            "cutoff": COLLECTION_CUTOFF.isoformat(),
            "lookback_hours": runtime.lookback_hours,
            "collected": len(records),
            "writes": 0,
            "updates": 0,
            "metadata_updates": 0,
            "merge_candidates": 0,
            "merge_updates": 0,
            "needs_review": 0,
            "skips": 0,
            "errors": 0,
            "dry_run_candidates": 0,
            "fixture_mode": self._fixture_mode_enabled(),
            "_errors": [],
        }
        for record in records:
            existing = await self._find_existing_record(record=record, noco=noco)
            existing_hash = self._source_hash_from_existing(existing)
            if existing_hash is None:
                existing_hash = self.state.get_source_hash(record.source_id)
            if existing_hash == record.source_hash:
                if (
                    runtime.write_mode == "write"
                    and noco.configured
                    and existing
                    and self._needs_merge_metadata(existing)
                ):
                    try:
                        await noco.upsert_record(record)
                        summary["metadata_updates"] += 1
                        self.state.upsert_source_state(
                            source_id=record.source_id,
                            source=record.source,
                            source_hash=record.source_hash,
                            payload=record.model_dump(mode="json"),
                            updated_at=record.last_collected_at,
                        )
                        continue
                    except Exception as exc:  # noqa: BLE001
                        summary["errors"] += 1
                        summary["_errors"].append(
                            {
                                "source_id": record.source_id,
                                "target_table": record.target_table,
                                "reason": f"{type(exc).__name__}: {exc}",
                            }
                        )
                        continue
                summary["skips"] += 1
                self.state.upsert_source_state(
                    source_id=record.source_id,
                    source=record.source,
                    source_hash=record.source_hash,
                    payload=record.model_dump(mode="json"),
                    updated_at=record.last_collected_at,
                )
                continue
            if runtime.write_mode == "dry-run":
                if existing is None:
                    candidates = await self._merge_candidates(record=record, noco=noco)
                    decision = decide_merge(record, candidates)
                    if decision.decision == "merge":
                        summary["merge_candidates"] += 1
                    elif decision.decision == "needs_review":
                        summary["needs_review"] += 1
                summary["dry_run_candidates"] += 1
                continue
            if not noco.configured:
                summary["errors"] += 1
                summary["_errors"].append(
                    {
                        "source_id": record.source_id,
                        "target_table": record.target_table,
                        "reason": "NOCO_API_TOKEN is not configured",
                    }
                )
                continue
            try:
                if existing is None:
                    candidates = await self._merge_candidates(record=record, noco=noco)
                    decision = decide_merge(record, candidates)
                    if decision.decision == "merge":
                        summary["merge_candidates"] += 1
                        target = self._target_candidate(candidates, decision.target_ext_id)
                        result = await noco.merge_record(record, target, decision)
                        summary["merge_updates"] += 1
                        self.state.upsert_source_state(
                            source_id=record.source_id,
                            source=record.source,
                            source_hash=record.source_hash,
                            payload=record.model_dump(mode="json"),
                            updated_at=record.last_collected_at,
                        )
                        continue
                    if decision.decision == "needs_review":
                        summary["needs_review"] += 1
                        record.normalized["merge_status"] = "needs_review"
                result = await noco.upsert_record(record)
                if result["action"] == "created":
                    summary["writes"] += 1
                else:
                    summary["updates"] += 1
                self.state.upsert_source_state(
                    source_id=record.source_id,
                    source=record.source,
                    source_hash=record.source_hash,
                    payload=record.model_dump(mode="json"),
                    updated_at=record.last_collected_at,
                )
            except Exception as exc:  # noqa: BLE001
                summary["errors"] += 1
                summary["_errors"].append(
                    {
                        "source_id": record.source_id,
                        "target_table": record.target_table,
                        "reason": f"{type(exc).__name__}: {exc}",
                    }
                )
        return summary

    async def _find_existing_record(self, *, record, noco: NocoDBClient) -> dict | None:
        if noco.configured:
            try:
                return await noco.find_existing_record(record.target_table, record.source_id)
            except Exception:  # noqa: BLE001
                return None
        return None

    def _source_hash_from_existing(self, existing: dict | None) -> str | None:
        if existing and existing.get("source_hash"):
            return str(existing["source_hash"])
        return None

    async def _merge_candidates(self, *, record, noco: NocoDBClient) -> list[dict]:
        finder = getattr(noco, "find_merge_candidates", None)
        if not finder:
            return []
        try:
            return await finder(record, limit=5)
        except Exception:  # noqa: BLE001
            return []

    def _target_candidate(
        self,
        candidates: list[dict],
        target_ext_id: str | None,
    ) -> dict:
        if target_ext_id:
            for candidate in candidates:
                if str(candidate.get("ext_id") or "") == target_ext_id:
                    return candidate
        if not candidates:
            raise RuntimeError("Merge decision did not include a target candidate")
        return candidates[0]

    def _needs_merge_metadata(self, existing: dict) -> bool:
        required = [
            "knowledge_unit_key",
            "canonical_title",
            "merge_status",
            "source_refs",
            "merged_source_count",
            "canonical_hash",
        ]
        if existing.get("ext_id", "").startswith("terms:"):
            required.extend(["structured_sections", "section_count"])
        return any(existing.get(field) in {None, ""} for field in required)

    def _fixture_mode_enabled(self) -> bool:
        return not any(
            [
                self.settings.slack_bot_token,
                self.settings.class101_admin_graphql_url,
                self.settings.class101_admin_authorization,
                self.settings.class101_refresh_token,
            ]
        )
