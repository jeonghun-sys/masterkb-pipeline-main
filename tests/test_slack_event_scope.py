from datetime import datetime

import pytest

from kb_pipeline.config import KST
from kb_pipeline.models import PipelineMode, PipelineScope
from kb_pipeline.pipelines.slack_pipeline import SlackPipeline


class FakeSlackClient:
    configured = True

    async def conversations_replies(
        self,
        *,
        channel_id: str,
        thread_ts: str,
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict:
        assert channel_id == "C01J93WPXN3"
        assert thread_ts == "1778136170.724039"
        return {
            "messages": [
                {
                    "type": "message",
                    "ts": "1778136170.724039",
                    "user": "U_PARENT",
                    "text": "[민원공유] 구독 환불 문의",
                },
                {
                    "type": "message",
                    "ts": "1778136270.724039",
                    "user": "U_REPLY",
                    "text": "환불 기준 확인 후 안내했습니다.",
                },
            ]
        }


class FakeLLM:
    async def normalize(self, *, source: str, payload: dict) -> dict:
        assert source == "slack_cs_data"
        assert payload["trigger_type"] == "slack_event"
        assert payload["channel"] == "cx-tck-complaints"
        return {
            "summary": "구독 환불 문의에 대한 상담 기준 공유",
            "category": "환불/취소",
            "intent": "구독 환불 문의",
            "customer_answer": "환불 기준 확인 후 안내했습니다.",
            "llm_status": "fake",
        }


@pytest.mark.asyncio
async def test_slack_pipeline_collects_only_scoped_thread_for_event_trigger():
    records = await SlackPipeline(
        slack=FakeSlackClient(),
        llm=FakeLLM(),
    ).collect(
        mode=PipelineMode.INCREMENTAL,
        limit=None,
        use_fixtures_when_unconfigured=False,
        scope=PipelineScope(
            channel_id="C01J93WPXN3",
            thread_ts="1778136170.724039",
            event_id="Ev123",
        ),
        trigger_type="slack_event",
        collected_at=datetime(2026, 5, 12, 12, 0, tzinfo=KST),
    )

    assert len(records) == 1
    assert records[0].source_id == "C01J93WPXN3:1778136170.724039"
    assert records[0].target_table == "slack_cs_data"
    assert records[0].source_reply_count == 1
