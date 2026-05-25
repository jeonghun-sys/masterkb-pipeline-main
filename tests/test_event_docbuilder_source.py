from datetime import datetime, timedelta

import pytest

from kb_pipeline.config import KST
from kb_pipeline.models import PipelineMode
from kb_pipeline.normalizers import event as event_normalizer
from kb_pipeline.pipelines.event_pipeline import EventPipeline


class FakeDocBuilder:
    configured = True

    def __init__(self) -> None:
        self.after_values: list[str | None] = []

    async def fetch_document_table(
        self,
        *,
        first: int = 20,
        after: str | None = None,
    ) -> dict:
        self.after_values.append(after)
        return {
            "edges": [
                {
                    "cursor": "cursor-1",
                    "node": {
                        "id": "doc-1",
                        "documentId": "doc-1",
                        "slug": "TVOD-2605-01",
                        "title": "TVOD-2605-01",
                        "version": 22,
                        "latestVersion": 22,
                        "isPublished": True,
                        "isDeleted": False,
                        "createdAt": "2026-05-11T02:57:00.000Z",
                        "publishedAt": "2026-05-11T02:57:00.000Z",
                    },
                },
                {
                    "cursor": "cursor-2",
                    "node": {
                        "id": "doc-old",
                        "documentId": "doc-old",
                        "slug": "old-promo",
                        "title": "old promo",
                        "version": 1,
                        "latestVersion": 1,
                        "isPublished": True,
                        "isDeleted": False,
                        "createdAt": "2026-04-01T00:00:00.000Z",
                        "publishedAt": "2026-04-01T00:00:00.000Z",
                    },
                },
            ],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        }

    async def fetch_document_by_slug(self, slug: str) -> dict:
        assert slug in {"TVOD-2605-01", "old-promo"}
        return {
            "documentId": "doc-1" if slug == "TVOD-2605-01" else "doc-old",
            "slug": slug,
            "title": slug,
            "version": 22,
            "latestVersion": 22,
            "isPublished": True,
            "isDeleted": False,
            "createdAt": "2026-05-11T02:57:00.000Z",
            "publishedAt": "2026-05-11T02:57:00.000Z",
            "content": (
                '<ImageBlock.InnerImage desktopSrc="https://cdn.class101.net/images/sample" />'
                '<a href="https://class101.net/ko/payment/select-subscription-plan">구독</a>'
            ),
            "hrefs": ["https://class101.net/ko/payment/select-subscription-plan"],
            "imageUrls": ["https://cdn.class101.net/images/sample"],
            "components": ["ImageBlock"],
            "url": "https://class101.net/ko/pages/TVOD-2605-01",
        }


class FakeOCR:
    async def extract_from_url(self, image_url: str) -> str:
        assert image_url == "https://cdn.class101.net/images/sample"
        return "5월 상시 선착순 프로모션. 5월 1일부터 5월 12일까지 진행됩니다."


class FakeLLM:
    async def normalize(self, *, source: str, payload: dict) -> dict:
        assert source == "event_promotion"
        assert "5월 상시 선착순 프로모션" in payload["ocr_text"]
        assert payload["document"]["slug"] in {"TVOD-2605-01", "old-promo"}
        return {
            "summary": "5월 상시 선착순 프로모션 안내",
            "category": "프로모션",
            "intent": "구독 이벤트 안내",
            "customer_answer": "5월 상시 선착순 혜택은 이벤트 기간 내 구독 시 적용됩니다.",
            "llm_status": "fake",
        }


class FailOnDetailDocBuilder(FakeDocBuilder):
    async def fetch_document_by_slug(self, slug: str) -> dict:
        raise AssertionError(f"unchanged document should not fetch detail: {slug}")


class FailOnOCR(FakeOCR):
    async def extract_from_url(self, image_url: str) -> str:
        raise AssertionError(f"unchanged document should not run OCR: {image_url}")


class FailOnLLM(FakeLLM):
    async def normalize(self, *, source: str, payload: dict) -> dict:
        raise AssertionError(f"unchanged document should not run LLM: {source} {payload}")


class FakeNocoExistingMetadata:
    configured = True

    async def find_existing_record(self, target_table: str, ext_id: str) -> dict | None:
        assert target_table == "event_promotion"
        if ext_id == "doc_builder:TVOD-2605-01":
            return {
                "Id": 365,
                "ext_id": "doc_builder:TVOD-2605-01",
                "source_updated_ts": "2026-05-11T02:57:00.000Z",
                "source_hash": "already-normalized",
            }
        return None


def test_event_document_filter_uses_published_at_recent_window():
    assert hasattr(event_normalizer, "include_event_document")
    include_event_document = event_normalizer.include_event_document
    now = datetime(2026, 5, 11, 12, 0, tzinfo=KST)
    recent = {
        "isPublished": True,
        "isDeleted": False,
        "publishedAt": "2026-05-01T00:00:00.000Z",
    }
    old = {**recent, "publishedAt": "2026-04-01T00:00:00.000Z"}
    unpublished = {**recent, "isPublished": False}
    deleted = {**recent, "isDeleted": True}

    assert include_event_document(recent, since=now - timedelta(days=14))
    assert not include_event_document(old, since=now - timedelta(days=14))
    assert not include_event_document(unpublished, since=now - timedelta(days=14))
    assert not include_event_document(deleted, since=now - timedelta(days=14))


def test_event_document_to_record_targets_event_promotion():
    assert hasattr(event_normalizer, "event_document_to_record")
    event_document_to_record = event_normalizer.event_document_to_record
    record = event_document_to_record(
        doc={
            "documentId": "doc-1",
            "slug": "TVOD-2605-01",
            "title": "TVOD-2605-01",
            "version": 22,
            "latestVersion": 22,
            "isPublished": True,
            "isDeleted": False,
            "publishedAt": "2026-05-11T02:57:00.000Z",
            "hrefs": ["https://class101.net/ko/payment/select-subscription-plan"],
            "imageUrls": ["https://cdn.class101.net/images/sample"],
            "url": "https://class101.net/ko/pages/TVOD-2605-01",
        },
        ocr_text="5월 상시 선착순 프로모션",
        collected_at=datetime(2026, 5, 11, 12, 0, tzinfo=KST),
        normalized={"summary": "5월 프로모션"},
    )

    assert record is not None
    assert record.source == "event_promotion"
    assert record.source_id == "doc_builder:TVOD-2605-01"
    assert record.target_table == "event_promotion"
    assert record.raw["source_kind"] == "doc_builder_document"
    assert record.raw["ocr_text"] == "5월 상시 선착순 프로모션"


@pytest.mark.asyncio
async def test_event_pipeline_collects_docbuilder_documents_for_event_promotion():
    records = await EventPipeline(
        docbuilder=FakeDocBuilder(),
        ocr=FakeOCR(),
        llm=FakeLLM(),
    ).collect(
        mode=PipelineMode.BACKFILL,
        limit=1,
        use_fixtures_when_unconfigured=False,
        now=datetime(2026, 5, 11, 12, 0, tzinfo=KST),
    )

    assert len(records) == 1
    record = records[0]
    assert record.source_id == "doc_builder:TVOD-2605-01"
    assert record.target_table == "event_promotion"
    assert record.normalized["summary"] == "5월 상시 선착순 프로모션 안내"
    assert record.url == "https://class101.net/ko/pages/TVOD-2605-01"


@pytest.mark.asyncio
async def test_event_pipeline_backfill_uses_collection_cutoff_for_docbuilder_documents():
    records = await EventPipeline(
        docbuilder=FakeDocBuilder(),
        ocr=FakeOCR(),
        llm=FakeLLM(),
    ).collect(
        mode=PipelineMode.BACKFILL,
        limit=None,
        use_fixtures_when_unconfigured=False,
        now=datetime(2026, 5, 11, 12, 0, tzinfo=KST),
    )

    assert [record.source_id for record in records] == [
        "doc_builder:TVOD-2605-01",
        "doc_builder:old-promo",
    ]


@pytest.mark.asyncio
async def test_event_pipeline_skips_docbuilder_ocr_and_llm_when_nocodb_metadata_unchanged():
    records = await EventPipeline(
        docbuilder=FailOnDetailDocBuilder(),
        ocr=FailOnOCR(),
        llm=FailOnLLM(),
        noco=FakeNocoExistingMetadata(),
    ).collect(
        mode=PipelineMode.INCREMENTAL,
        limit=1,
        use_fixtures_when_unconfigured=False,
        now=datetime(2026, 5, 11, 12, 0, tzinfo=KST),
    )

    assert records == []
