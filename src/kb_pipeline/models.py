from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class PipelineMode(StrEnum):
    SMOKE = "smoke"
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"


class TriggerType(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    SLACK_EVENT = "slack_event"


WriteMode = Literal["dry-run", "write"]


class PipelineScope(BaseModel):
    channel_id: str | None = None
    thread_ts: str | None = None
    message_ts: str | None = None
    event_id: str | None = None
    document_id: str | None = None
    slug: str | None = None


class PipelineRuntime(BaseModel):
    mode: PipelineMode
    trigger_type: TriggerType = TriggerType.MANUAL
    write_mode: WriteMode = "dry-run"
    target_sources: list[str] = Field(
        default_factory=lambda: ["slack", "event", "docbuilder", "terms"],
    )
    limit: int | None = None
    lookback_hours: int = 6
    use_fixtures_when_unconfigured: bool = True
    scope: PipelineScope | None = None


class SourceRecord(BaseModel):
    source: str
    source_id: str
    target_table: str
    title: str
    raw: dict[str, Any]
    normalized: dict[str, Any]
    source_updated_ts: str | None = None
    source_latest_reply_ts: str | None = None
    source_reply_count: int = 0
    source_hash: str
    last_collected_at: str
    url: str | None = None
    thread_ref: str | None = None


class PipelineResult(BaseModel):
    mode: PipelineMode
    trigger_type: TriggerType = TriggerType.MANUAL
    write_mode: WriteMode
    scope: PipelineScope | None = None
    summary: dict[str, Any]
    records: list[SourceRecord] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class UpsertDecision(BaseModel):
    source_id: str
    target_table: str
    action: Literal["create_or_update", "skip_unchanged", "dry_run", "error"]
    reason: str | None = None
