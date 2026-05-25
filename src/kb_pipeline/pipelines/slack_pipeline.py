from __future__ import annotations

from datetime import datetime, timedelta

from kb_pipeline.clients.llm import LLMClient
from kb_pipeline.clients.slack import SlackClient
from kb_pipeline.config import CHANNELS, COLLECTION_CUTOFF
from kb_pipeline.fixtures import collected_at_sample, sample_slack_thread
from kb_pipeline.models import PipelineMode, PipelineScope, SourceRecord
from kb_pipeline.normalizers.common import parse_slack_ts
from kb_pipeline.normalizers.slack import is_noise_message, slack_thread_to_record


class SlackPipeline:
    def __init__(self, *, slack: SlackClient, llm: LLMClient) -> None:
        self.slack = slack
        self.llm = llm

    async def collect(
        self,
        *,
        mode: PipelineMode,
        limit: int | None,
        use_fixtures_when_unconfigured: bool,
        scope: PipelineScope | None = None,
        trigger_type: str = "manual",
        collected_at: datetime | None = None,
        lookback_hours: int = 6,
    ) -> list[SourceRecord]:
        collected_at = collected_at or datetime.now(tz=COLLECTION_CUTOFF.tzinfo)
        if self.slack.configured:
            if scope and scope.channel_id and scope.thread_ts:
                return await self._collect_thread_scope(
                    scope=scope,
                    trigger_type=trigger_type,
                    collected_at=collected_at,
                )
            return await self._collect_live(
                mode=mode,
                limit=limit,
                lookback_hours=lookback_hours,
                collected_at=collected_at,
            )
        if use_fixtures_when_unconfigured:
            return await self._collect_fixtures(limit=limit)
        return []

    async def _collect_fixtures(self, *, limit: int | None) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        for channel_id, channel in CHANNELS.items():
            parent, replies = sample_slack_thread(channel_id)
            meaningful_replies = [
                reply for reply in replies if not is_noise_message(str(reply.get("text", "")))
            ]
            normalized = await self.llm.normalize(
                source=channel.target_table,
                payload={
                    "title": str(parent.get("text", "")).splitlines()[0],
                    "text": parent.get("text", ""),
                    "replies": [reply.get("text", "") for reply in meaningful_replies],
                    "noise_removed": len(replies) - len(meaningful_replies),
                    "channel": channel.name,
                },
            )
            record = slack_thread_to_record(
                channel_id=channel_id,
                parent=parent,
                replies=replies,
                collected_at=collected_at_sample(),
                normalized=normalized,
            )
            if record:
                records.append(record)
            if limit and len(records) >= limit:
                break
        return records

    async def _collect_live(
        self,
        *,
        mode: PipelineMode,
        limit: int | None,
        lookback_hours: int,
        collected_at: datetime,
    ) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        oldest_dt = COLLECTION_CUTOFF
        if mode == PipelineMode.INCREMENTAL:
            oldest_dt = max(COLLECTION_CUTOFF, collected_at - timedelta(hours=lookback_hours))
        oldest = str(oldest_dt.timestamp())
        for channel_id, channel in CHANNELS.items():
            cursor: str | None = None
            while True:
                page = await self.slack.conversations_history(
                    channel_id=channel_id,
                    oldest=oldest,
                    limit=200,
                    cursor=cursor,
                )
                for message in page.get("messages", []):
                    parent_ts = str(message.get("thread_ts") or message.get("ts") or "")
                    if parent_ts != str(message.get("ts")):
                        continue
                    if parse_slack_ts(parent_ts) < COLLECTION_CUTOFF:
                        continue
                    replies_payload = await self.slack.conversations_replies(
                        channel_id=channel_id,
                        thread_ts=parent_ts,
                        limit=200,
                    )
                    replies = replies_payload.get("messages", [])[1:]
                    meaningful_replies = [
                        reply
                        for reply in replies
                        if not is_noise_message(str(reply.get("text", "")))
                    ]
                    normalized = await self.llm.normalize(
                        source=channel.target_table,
                        payload={
                            "title": str(message.get("text", "")).splitlines()[0],
                            "text": message.get("text", ""),
                            "replies": [
                                reply.get("text", "") for reply in meaningful_replies
                            ],
                            "noise_removed": len(replies) - len(meaningful_replies),
                            "channel": channel.name,
                            "mode": mode.value,
                        },
                    )
                    record = slack_thread_to_record(
                        channel_id=channel_id,
                        parent=message,
                        replies=replies,
                        collected_at=collected_at,
                        normalized=normalized,
                    )
                    if record:
                        records.append(record)
                    if limit and len(records) >= limit:
                        return records
                cursor = page.get("response_metadata", {}).get("next_cursor") or None
                if not cursor:
                    break
        return records

    async def _collect_thread_scope(
        self,
        *,
        scope: PipelineScope,
        trigger_type: str,
        collected_at: datetime,
    ) -> list[SourceRecord]:
        if not scope.channel_id or not scope.thread_ts:
            return []
        channel = CHANNELS.get(scope.channel_id)
        if not channel:
            return []
        replies_payload = await self.slack.conversations_replies(
            channel_id=scope.channel_id,
            thread_ts=scope.thread_ts,
            limit=200,
        )
        messages = replies_payload.get("messages", [])
        if not messages:
            return []
        parent = messages[0]
        replies = messages[1:]
        meaningful_replies = [
            reply for reply in replies if not is_noise_message(str(reply.get("text", "")))
        ]
        normalized = await self.llm.normalize(
            source=channel.target_table,
            payload={
                "title": str(parent.get("text", "")).splitlines()[0],
                "text": parent.get("text", ""),
                "replies": [reply.get("text", "") for reply in meaningful_replies],
                "noise_removed": len(replies) - len(meaningful_replies),
                "channel": channel.name,
                "trigger_type": trigger_type,
                "event_id": scope.event_id,
                "message_ts": scope.message_ts,
            },
        )
        record = slack_thread_to_record(
            channel_id=scope.channel_id,
            parent=parent,
            replies=replies,
            collected_at=collected_at,
            normalized=normalized,
        )
        return [record] if record else []
