from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from kb_pipeline.config import CHANNELS, COLLECTION_CUTOFF
from kb_pipeline.models import PipelineMode, PipelineScope, TriggerType
from kb_pipeline.pipelines.runner import PipelineRunner
from kb_pipeline.settings import get_settings

app = FastAPI(title="KB Pipeline", version="0.1.0")


class RunRequest(BaseModel):
    mode: PipelineMode = PipelineMode.SMOKE
    write_mode: str = "dry-run"
    target_sources: list[str] | None = None
    limit: int | None = None
    lookback_hours: int | None = None
    scope: PipelineScope | None = None


class ScheduledRunRequest(BaseModel):
    target_sources: list[str] = ["slack", "event", "docbuilder", "terms"]
    limit: int | None = None
    lookback_hours: int | None = 48
    write_mode: str = "write"


def require_pipeline_token(
    x_pipeline_token: Annotated[str | None, Header(alias="X-Pipeline-Token")] = None,
) -> None:
    expected_token = (get_settings().pipeline_webhook_token or "").strip()
    if not expected_token:
        return
    if not x_pipeline_token or not secrets.compare_digest(x_pipeline_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid pipeline token",
        )


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "service": "kb-pipeline",
        "cutoff": COLLECTION_CUTOFF.isoformat(),
        "channels": len(CHANNELS),
    }


@app.post("/runs", dependencies=[Depends(require_pipeline_token)])
def run_pipeline(request: RunRequest) -> dict[str, object]:
    runner = PipelineRunner()
    result = runner.run(
        mode=request.mode,
        trigger_type=TriggerType.MANUAL,
        write_mode="write" if request.write_mode == "write" else "dry-run",
        target_sources=request.target_sources,
        limit=request.limit,
        lookback_hours=request.lookback_hours,
        scope=request.scope,
    )
    return result.model_dump()


@app.post("/runs/scheduled", dependencies=[Depends(require_pipeline_token)])
def run_scheduled_pipeline(request: ScheduledRunRequest | None = None) -> dict[str, object]:
    payload = request or ScheduledRunRequest()
    runner = PipelineRunner()
    result = runner.run(
        mode=PipelineMode.INCREMENTAL,
        trigger_type=TriggerType.SCHEDULE,
        write_mode="write" if payload.write_mode == "write" else "dry-run",
        target_sources=payload.target_sources,
        limit=payload.limit,
        lookback_hours=payload.lookback_hours,
    )
    return result.model_dump()


@app.post("/webhooks/slack", dependencies=[Depends(require_pipeline_token)])
def slack_webhook(payload: dict) -> dict[str, object]:
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    if event.get("type") != "message":
        return {"ok": True, "ignored": "non_message_event"}
    if event.get("subtype") in {"channel_join", "channel_leave", "bot_message"}:
        return {"ok": True, "ignored": event.get("subtype")}

    channel_id = str(event.get("channel") or "")
    message_ts = str(event.get("ts") or "")
    thread_ts = str(event.get("thread_ts") or message_ts)
    if not channel_id or not thread_ts:
        return {"ok": False, "ignored": "missing_channel_or_thread_ts"}

    runner = PipelineRunner()
    result = runner.run(
        mode=PipelineMode.INCREMENTAL,
        trigger_type=TriggerType.SLACK_EVENT,
        write_mode="write",
        target_sources=["slack"],
        limit=1,
        scope=PipelineScope(
            channel_id=channel_id,
            thread_ts=thread_ts,
            message_ts=message_ts or None,
            event_id=str(payload.get("event_id") or "") or None,
        ),
    )
    return {"ok": True, "result": result.model_dump()}
