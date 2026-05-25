from datetime import datetime
from zoneinfo import ZoneInfo

from kb_pipeline.clients.llm import LLMClient
from kb_pipeline.config import CHANNELS, COLLECTION_CUTOFF
from kb_pipeline.models import PipelineMode, PipelineRuntime, SourceRecord
from kb_pipeline.normalizers.common import build_source_hash, is_after_cutoff


def test_collection_cutoff_is_april_first_kst():
    assert COLLECTION_CUTOFF == datetime(2026, 4, 1, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))


def test_slack_channel_routes_to_expected_tables():
    assert CHANNELS["C01F3FELHL5"].target_table == "class101_changelog"
    assert CHANNELS["C05U3LUPR6V"].target_table == "class101_promotion"
    assert CHANNELS["C08BGKAQM33"].target_table == "product_issue"
    assert CHANNELS["C01J93WPXN3"].target_table == "slack_cs_data"


def test_cutoff_uses_parent_thread_created_at_for_slack():
    before = datetime(2026, 3, 31, 23, 59, 59, tzinfo=ZoneInfo("Asia/Seoul"))
    after = datetime(2026, 4, 1, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))

    assert not is_after_cutoff(before)
    assert is_after_cutoff(after)


def test_source_hash_is_stable_and_sensitive_to_meaningful_content():
    first = build_source_hash(
        {
            "title": "A",
            "body": "original",
            "replies": [{"text": "meaningful"}],
        }
    )
    same = build_source_hash(
        {
            "replies": [{"text": "meaningful"}],
            "body": "original",
            "title": "A",
        }
    )
    changed = build_source_hash(
        {
            "title": "A",
            "body": "original",
            "replies": [{"text": "meaningful update"}],
        }
    )

    assert first == same
    assert first != changed


def test_pipeline_runtime_supports_smoke_backfill_incremental_and_dry_run():
    runtime = PipelineRuntime(mode=PipelineMode.SMOKE, write_mode="dry-run", limit=1)

    assert runtime.mode == PipelineMode.SMOKE
    assert runtime.write_mode == "dry-run"
    assert runtime.limit == 1


def test_source_record_contains_tracking_fields():
    record = SourceRecord(
        source="slack",
        source_id="C01J93WPXN3:1775000000.000000",
        target_table="slack_cs_data",
        title="테스트",
        raw={"text": "raw"},
        normalized={"summary": "정제"},
        source_updated_ts="1775000000.000000",
        source_latest_reply_ts="1775000001.000000",
        source_reply_count=1,
        source_hash="abc",
        last_collected_at="2026-05-11T12:00:00+09:00",
    )

    assert record.source_hash == "abc"
    assert record.source_reply_count == 1


def test_llm_parser_accepts_json_code_fence():
    client = LLMClient(api_key=None, model="test")
    parsed = client._parse_json_object(
        '```json\n{"summary":"요약","changes":["변경"]}\n```'
    )

    assert parsed["summary"] == "요약"
    assert parsed["changes"] == ["변경"]
