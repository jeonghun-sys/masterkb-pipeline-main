import httpx
import pytest

from kb_pipeline.models import PipelineMode, PipelineRuntime, SourceRecord
from kb_pipeline.pipelines.runner import PipelineRunner


def test_write_mode_without_nocodb_token_returns_errors_without_state_update(tmp_path, monkeypatch):
    state_db = tmp_path / "state.sqlite3"
    monkeypatch.setenv("KB_PIPELINE_STATE_DB", str(state_db))
    from kb_pipeline.settings import get_settings

    get_settings.cache_clear()
    runner = PipelineRunner()

    result = runner.run(
        mode=PipelineMode.SMOKE,
        write_mode="write",
        target_sources=["event"],
        limit=1,
    )

    assert result.summary["collected"] == 1
    assert result.summary["writes"] == 0
    assert result.summary["updates"] == 0
    assert result.summary["errors"] == 1
    assert result.errors[0]["reason"] == "NOCO_API_TOKEN is not configured"


def test_existing_source_hash_is_skipped_in_incremental_style_run(tmp_path, monkeypatch):
    state_db = tmp_path / "state.sqlite3"
    monkeypatch.setenv("KB_PIPELINE_STATE_DB", str(state_db))
    from kb_pipeline.settings import get_settings

    get_settings.cache_clear()
    runner = PipelineRunner()
    first = runner.run(
        mode=PipelineMode.SMOKE,
        write_mode="dry-run",
        target_sources=["event"],
        limit=1,
    )
    record = first.records[0]
    runner.state.upsert_source_state(
        source_id=record.source_id,
        source=record.source,
        source_hash=record.source_hash,
        payload=record.model_dump(mode="json"),
        updated_at=record.last_collected_at,
    )

    second = runner.run(
        mode=PipelineMode.INCREMENTAL,
        write_mode="dry-run",
        target_sources=["event"],
        limit=1,
    )

    assert second.summary["collected"] == 1
    assert second.summary["skips"] == 1
    assert second.summary["dry_run_candidates"] == 0


@pytest.mark.asyncio
async def test_nocodb_source_hash_is_used_as_primary_skip_state(tmp_path, monkeypatch):
    state_db = tmp_path / "state.sqlite3"
    monkeypatch.setenv("KB_PIPELINE_STATE_DB", str(state_db))
    from kb_pipeline.settings import get_settings

    get_settings.cache_clear()
    record = SourceRecord(
        source="event_promotion",
        source_id="doc-existing",
        target_table="event_promotion",
        title="기존 문서",
        raw={"documentId": "doc-existing"},
        normalized={"summary": "이미 적재된 문서"},
        source_updated_ts="2026-05-11T02:57:00.000Z",
        source_hash="same-hash",
        last_collected_at="2026-05-12T09:00:00+09:00",
    )

    class FakeNoco:
        configured = True
        upsert_called = False

        async def find_existing_record(self, target_table: str, ext_id: str) -> dict | None:
            assert target_table == "event_promotion"
            assert ext_id == "doc-existing"
            return {"Id": 123, "ext_id": ext_id, "source_hash": "same-hash"}

        async def upsert_record(self, _record: SourceRecord) -> dict:
            self.upsert_called = True
            raise AssertionError("unchanged NocoDB row should not be upserted")

    noco = FakeNoco()
    runner = PipelineRunner()
    summary = await runner._process_records(
        runtime=PipelineRuntime(
            mode=PipelineMode.INCREMENTAL,
            write_mode="dry-run",
            target_sources=["event"],
        ),
        records=[record],
        noco=noco,
    )

    assert summary["skips"] == 1
    assert summary["dry_run_candidates"] == 0
    assert summary["writes"] == 0
    assert summary["updates"] == 0
    assert noco.upsert_called is False


@pytest.mark.asyncio
async def test_same_source_hash_updates_missing_merge_metadata(tmp_path, monkeypatch):
    state_db = tmp_path / "state.sqlite3"
    monkeypatch.setenv("KB_PIPELINE_STATE_DB", str(state_db))
    from kb_pipeline.settings import get_settings

    get_settings.cache_clear()
    record = SourceRecord(
        source="slack",
        source_id="C01F3FELHL5:1777537730.396179",
        target_table="class101_changelog",
        title="정산 월렛 전환",
        raw={"channel": "all-breaking-changes"},
        normalized={
            "summary": "크리에이터 정산 월렛 전환 안내",
            "knowledge_unit_key": "creator_settlement_wallet_integration",
            "canonical_title": "크리에이터 정산 월렛 전환 안내",
        },
        source_updated_ts="1777537730.396179",
        source_hash="same-hash",
        last_collected_at="2026-05-14T14:00:00+09:00",
        thread_ref="C01F3FELHL5:1777537730.396179",
    )

    class FakeNoco:
        configured = True

        def __init__(self) -> None:
            self.upsert_called = False

        async def find_existing_record(self, target_table: str, ext_id: str) -> dict | None:
            return {"Id": 41, "ext_id": ext_id, "source_hash": "same-hash"}

        async def upsert_record(self, _record: SourceRecord) -> dict:
            self.upsert_called = True
            return {"action": "updated", "response": {"Id": 41}}

    noco = FakeNoco()
    runner = PipelineRunner()
    summary = await runner._process_records(
        runtime=PipelineRuntime(
            mode=PipelineMode.INCREMENTAL,
            write_mode="write",
            target_sources=["slack"],
        ),
        records=[record],
        noco=noco,
    )

    assert summary["metadata_updates"] == 1
    assert summary["skips"] == 0
    assert noco.upsert_called is True


@pytest.mark.asyncio
async def test_same_terms_hash_updates_missing_structured_sections(tmp_path, monkeypatch):
    state_db = tmp_path / "state.sqlite3"
    monkeypatch.setenv("KB_PIPELINE_STATE_DB", str(state_db))
    from kb_pipeline.settings import get_settings

    get_settings.cache_clear()
    record = SourceRecord(
        source="class101_terms",
        source_id="terms:refund",
        target_table="class101_terms",
        title="환불정책",
        raw={
            "slug": "refund",
            "content_text": "환불정책",
            "sections": [{"heading": "환불정책", "level": 1, "items": ["환불정책"]}],
        },
        normalized={
            "summary": "환불정책",
            "knowledge_unit_key": "class101_terms_refund",
            "canonical_title": "CLASS101 환불정책",
        },
        source_updated_ts="2026-04-19T15:00:00.000Z",
        source_hash="same-hash",
        last_collected_at="2026-05-14T14:00:00+09:00",
    )

    class FakeNoco:
        configured = True

        def __init__(self) -> None:
            self.upsert_called = False

        async def find_existing_record(self, target_table: str, ext_id: str) -> dict | None:
            return {
                "Id": 42,
                "ext_id": ext_id,
                "source_hash": "same-hash",
                "knowledge_unit_key": "class101_terms_refund",
                "canonical_title": "CLASS101 환불정책",
                "merge_status": "standalone",
                "source_refs": '["terms:refund"]',
                "merged_source_count": 1,
                "canonical_hash": "same-hash",
                "structured_sections": "",
            }

        async def upsert_record(self, _record: SourceRecord) -> dict:
            self.upsert_called = True
            return {"action": "updated", "response": {"Id": 42}}

    noco = FakeNoco()
    runner = PipelineRunner()
    summary = await runner._process_records(
        runtime=PipelineRuntime(
            mode=PipelineMode.INCREMENTAL,
            write_mode="write",
            target_sources=["terms"],
        ),
        records=[record],
        noco=noco,
    )

    assert summary["metadata_updates"] == 1
    assert summary["skips"] == 0
    assert noco.upsert_called is True


@pytest.mark.asyncio
async def test_unique_conflict_during_create_can_be_retried_as_patch(monkeypatch):
    from kb_pipeline.clients.nocodb import NocoDBClient

    record = SourceRecord(
        source="event_promotion",
        source_id="doc-race",
        target_table="event_promotion",
        title="동시 실행 문서",
        raw={"documentId": "doc-race"},
        normalized={"summary": "동시 실행 중 생성된 문서"},
        source_updated_ts="2026-05-11T02:57:00.000Z",
        source_hash="race-hash",
        last_collected_at="2026-05-12T09:00:00+09:00",
    )

    class FakeResponse:
        def __init__(self, status_code: int, payload: dict, text: str = "") -> None:
            self.status_code = status_code
            self._payload = payload
            self.text = text
            self.request = httpx.Request("POST", "https://noco.test")

        def json(self) -> dict:
            return self._payload

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"{self.status_code} error",
                    request=self.request,
                    response=self,
                )

    class FakeAsyncClient:
        post_calls = 0
        patch_calls = 0

        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *args, **kwargs):
            self.__class__.post_calls += 1
            return FakeResponse(422, {"msg": "Unique constraint failed"}, "unique constraint")

        async def patch(self, *args, **kwargs):
            self.__class__.patch_calls += 1
            assert kwargs["json"]["Id"] == 77
            return FakeResponse(200, {"Id": 77, "ext_id": "doc-race"})

    client = NocoDBClient(base_url="https://noco.test", token="token")

    async def fake_find_existing_record(target_table: str, ext_id: str) -> dict | None:
        assert target_table == "event_promotion"
        assert ext_id == "doc-race"
        if FakeAsyncClient.post_calls == 0:
            return None
        return {"Id": 77, "ext_id": "doc-race"}

    monkeypatch.setattr("kb_pipeline.clients.nocodb.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(client, "find_existing_record", fake_find_existing_record)

    result = await client.upsert_record(record)

    assert result["action"] == "updated_after_unique_conflict"
    assert FakeAsyncClient.post_calls == 1
    assert FakeAsyncClient.patch_calls == 1


@pytest.mark.asyncio
async def test_new_source_with_same_knowledge_unit_merges_existing_row(tmp_path, monkeypatch):
    state_db = tmp_path / "state.sqlite3"
    monkeypatch.setenv("KB_PIPELINE_STATE_DB", str(state_db))
    from kb_pipeline.settings import get_settings

    get_settings.cache_clear()
    record = SourceRecord(
        source="slack",
        source_id="C05U3LUPR6V:1779000000.000001",
        target_table="class101_promotion",
        title="구독 환불 캐시백 안내",
        raw={"channel": "all-promotion-sharing", "parent": {"text": "환불 예정 금액 50% 캐시백"}},
        normalized={
            "summary": "구독 중도 환불 유저에게 환불 예정 금액의 50% 캐시백을 제안합니다.",
            "category": "환불",
            "intent": "구독 환불 캐시백 정책문의",
            "customer_answer": "구독 환불 플로우에서 캐시백 제안이 노출될 수 있습니다.",
            "knowledge_unit_key": "subscription_refund_cashback_50pct",
            "canonical_title": "구독 중도 환불 유저 대상 50% 캐시백 제안",
            "core_facts": ["환불 예정 금액의 50% 캐시백", "구독 환불 플로우 진입 유저 대상"],
        },
        source_updated_ts="1779000000.000001",
        source_hash="new-source-hash",
        last_collected_at="2026-05-14T14:00:00+09:00",
        thread_ref="C05U3LUPR6V:1779000000.000001",
    )

    class FakeNoco:
        configured = True

        def __init__(self) -> None:
            self.upsert_called = False
            self.merge_called = False

        async def find_existing_record(self, target_table: str, ext_id: str) -> dict | None:
            assert target_table == "class101_promotion"
            assert ext_id == "C05U3LUPR6V:1779000000.000001"
            return None

        async def find_merge_candidates(self, _record: SourceRecord, limit: int = 5) -> list[dict]:
            return [
                {
                    "Id": 42,
                    "ext_id": "C05U3LUPR6V:1778000000.000001",
                    "Title": "구독 중도 환불 유저 대상 50% 캐시백 제안",
                    "summary": (
                        "구독 중도 환불 유저에게 환불 예정 금액의 50%를 "
                        "캐시백으로 제안합니다."
                    ),
                    "knowledge_unit_key": "subscription_refund_cashback_50pct",
                    "source_hash": "old-source-hash",
                    "source_refs": '["C05U3LUPR6V:1778000000.000001"]',
                }
            ][:limit]

        async def merge_record(self, _record: SourceRecord, existing: dict, decision) -> dict:
            self.merge_called = True
            assert existing["Id"] == 42
            assert decision.decision == "merge"
            assert decision.target_ext_id == "C05U3LUPR6V:1778000000.000001"
            return {"action": "merged", "response": {"Id": 42}}

        async def upsert_record(self, _record: SourceRecord) -> dict:
            self.upsert_called = True
            raise AssertionError("similar knowledge unit should merge, not create")

    noco = FakeNoco()
    runner = PipelineRunner()
    summary = await runner._process_records(
        runtime=PipelineRuntime(
            mode=PipelineMode.INCREMENTAL,
            write_mode="write",
            target_sources=["slack"],
        ),
        records=[record],
        noco=noco,
    )

    assert summary["writes"] == 0
    assert summary["updates"] == 0
    assert summary["merge_updates"] == 1
    assert summary["merge_candidates"] == 1
    assert summary["errors"] == 0
    assert noco.merge_called is True
    assert noco.upsert_called is False
