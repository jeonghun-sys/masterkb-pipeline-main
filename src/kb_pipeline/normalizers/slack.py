from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from kb_pipeline.config import CHANNELS
from kb_pipeline.models import SourceRecord
from kb_pipeline.normalizers.common import build_source_hash, is_after_cutoff, parse_slack_ts

JOIN_LEAVE_PATTERNS = (
    re.compile(r"joined the channel", re.IGNORECASE),
    re.compile(r"left the channel", re.IGNORECASE),
    re.compile(r"님이 채널에 참여함"),
    re.compile(r"님이 채널에서 나감"),
)


def is_noise_message(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return True
    if any(pattern.search(normalized) for pattern in JOIN_LEAVE_PATTERNS):
        return True
    if normalized in {"확인", "감사합니다", "네", "넵", "👍", "+1"}:
        return True
    return False


def slack_thread_to_record(
    *,
    channel_id: str,
    parent: dict[str, Any],
    replies: list[dict[str, Any]],
    collected_at: datetime,
    normalized: dict[str, Any] | None = None,
) -> SourceRecord | None:
    parent_ts = str(parent.get("ts", ""))
    if not parent_ts:
        return None
    if not is_after_cutoff(parse_slack_ts(parent_ts)):
        return None

    channel = CHANNELS[channel_id]
    meaningful_replies = [
        reply for reply in replies if not is_noise_message(str(reply.get("text", "")))
    ]
    meaningful_payload = {
        "channel": channel.name,
        "parent": parent.get("text", ""),
        "replies": [reply.get("text", "") for reply in meaningful_replies],
    }
    source_hash = build_source_hash(meaningful_payload)
    latest_reply_ts = max([parent_ts, *[str(reply.get("ts", parent_ts)) for reply in replies]])
    title = str(parent.get("text", "")).strip().splitlines()[0][:120] or channel.name

    return SourceRecord(
        source="slack",
        source_id=f"{channel_id}:{parent_ts}",
        target_table=channel.target_table,
        title=title,
        raw={"channel": channel.name, "parent": parent, "replies": replies},
        normalized=normalized
        or {
            "summary": title,
            "noise_removed": len(replies) - len(meaningful_replies),
        },
        source_updated_ts=parent_ts,
        source_latest_reply_ts=latest_reply_ts,
        source_reply_count=len(replies),
        source_hash=source_hash,
        last_collected_at=collected_at.isoformat(),
        url=f"https://101inc.slack.com/archives/{channel_id}/p{parent_ts.replace('.', '')}",
        thread_ref=f"{channel_id}:{parent_ts}",
    )
