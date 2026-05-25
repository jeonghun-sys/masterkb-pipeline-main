from datetime import datetime, timedelta

import pytest

from kb_pipeline.config import COLLECTION_CUTOFF, KST
from kb_pipeline.models import PipelineMode
from kb_pipeline.pipelines.slack_pipeline import SlackPipeline


class HistoryOnlySlackClient:
    configured = True

    def __init__(self) -> None:
        self.oldests: list[float] = []

    async def conversations_history(
        self,
        *,
        channel_id: str,
        oldest: str,
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict:
        self.oldests.append(float(oldest))
        return {"messages": []}

    async def conversations_replies(
        self,
        *,
        channel_id: str,
        thread_ts: str,
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict:
        raise AssertionError("empty history should not fetch replies")


class UnusedLLM:
    async def normalize(self, *, source: str, payload: dict) -> dict:
        raise AssertionError("empty history should not run LLM")


@pytest.mark.asyncio
async def test_slack_incremental_history_uses_lookback_window():
    slack = HistoryOnlySlackClient()
    collected_at = datetime(2026, 5, 14, 12, 0, tzinfo=KST)

    records = await SlackPipeline(slack=slack, llm=UnusedLLM()).collect(
        mode=PipelineMode.INCREMENTAL,
        limit=None,
        use_fixtures_when_unconfigured=False,
        lookback_hours=24,
        collected_at=collected_at,
    )

    expected_oldest = (collected_at - timedelta(hours=24)).timestamp()
    assert records == []
    assert slack.oldests
    assert all(oldest == expected_oldest for oldest in slack.oldests)


@pytest.mark.asyncio
async def test_slack_backfill_history_uses_collection_cutoff():
    slack = HistoryOnlySlackClient()

    records = await SlackPipeline(slack=slack, llm=UnusedLLM()).collect(
        mode=PipelineMode.BACKFILL,
        limit=None,
        use_fixtures_when_unconfigured=False,
        lookback_hours=24,
        collected_at=datetime(2026, 5, 14, 12, 0, tzinfo=KST),
    )

    assert records == []
    assert slack.oldests
    assert all(oldest == COLLECTION_CUTOFF.timestamp() for oldest in slack.oldests)
