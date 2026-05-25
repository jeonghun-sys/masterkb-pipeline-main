import html
import json
from datetime import datetime

import pytest

from kb_pipeline.config import KST
from kb_pipeline.models import PipelineMode
from kb_pipeline.normalizers.terms import extract_current_terms_document, terms_to_record
from kb_pipeline.pipelines.terms_pipeline import TermsPipeline


def make_terms_html(*, slug: str = "refund", content: str | None = None) -> str:
    term_ref = 'TermsV2:{"slug":"refund","serviceRegion":"KR"}'
    version_ref = "TermsVersion:1082"
    payload = {
        "props": {
            "pageProps": {"match": {"params": {"slug": slug}}},
            "apolloState": {
                "data": {
                    "ROOT_QUERY": {
                        'termV2BySlug({"slug":"refund"})': {"__ref": term_ref},
                    },
                    term_ref: {
                        "__typename": "TermsV2",
                        "slug": "refund",
                        "currentVersion": {"__ref": version_ref},
                    },
                    version_ref: {
                        "__typename": "TermsVersion",
                        "id": "1082",
                        "version": "2026-04-19",
                        "effectiveFrom": "2026-04-19T15:00:00.000Z",
                        "content": content
                        or "<h1>환불정책</h1><p>구독 상품은 조건에 따라 환불됩니다.</p>",
                    },
                }
            },
        }
    }
    encoded = html.escape(json.dumps(payload, ensure_ascii=False))
    return f'<html><script id="__NEXT_DATA__" type="application/json">{encoded}</script></html>'


def test_extract_current_terms_document_from_next_data():
    doc = extract_current_terms_document(
        html_text=make_terms_html(),
        slug="refund",
        title="환불정책",
        url="https://class101.net/ko/docs/terms/refund?viewMode=svod",
    )

    assert doc["slug"] == "refund"
    assert doc["title"] == "환불정책"
    assert doc["version_id"] == "1082"
    assert doc["version"] == "2026-04-19"
    assert doc["effectiveFrom"] == "2026-04-19T15:00:00.000Z"
    assert "구독 상품은 조건에 따라 환불됩니다." in doc["content_text"]
    assert doc["sections"] == [
        {
            "heading": "환불정책",
            "level": 1,
            "items": ["구독 상품은 조건에 따라 환불됩니다."],
        }
    ]
    assert "## 환불정책" in doc["section_markdown"]


def test_terms_to_record_targets_class101_terms_table():
    doc = extract_current_terms_document(
        html_text=make_terms_html(),
        slug="refund",
        title="환불정책",
        url="https://class101.net/ko/docs/terms/refund?viewMode=svod",
    )

    record = terms_to_record(
        doc=doc,
        collected_at=datetime(2026, 5, 14, 12, 0, tzinfo=KST),
        normalized={
            "summary": "구독 상품 환불 기준",
            "category": "약관",
            "intent": "환불정책",
            "knowledge_unit_key": "class101_terms_refund",
            "canonical_title": "CLASS101 환불정책",
        },
    )

    assert record.source == "class101_terms"
    assert record.source_id == "terms:refund"
    assert record.target_table == "class101_terms"
    assert record.source_updated_ts == "2026-04-19T15:00:00.000Z"
    assert record.url == "https://class101.net/ko/docs/terms/refund?viewMode=svod"
    assert record.raw["content_text"]


class FakeTermsClient:
    async def fetch(self, url: str) -> str:
        return make_terms_html()


class FakeLLM:
    async def normalize(self, *, source: str, payload: dict) -> dict:
        assert source == "class101_terms"
        assert payload["terms_key"] == "refund"
        assert "구독 상품은 조건에 따라 환불됩니다." in payload["body"]
        return {
            "summary": "구독 상품 환불 기준",
            "category": "약관",
            "intent": "환불정책",
            "changes": ["구독 상품은 조건에 따라 환불됩니다."],
            "customer_answer": "환불정책은 구독 상품의 조건별 환불 기준을 안내합니다.",
            "knowledge_unit_key": "class101_terms_refund",
            "canonical_title": "CLASS101 환불정책",
            "llm_status": "fake",
        }


class FailOnLLM(FakeLLM):
    async def normalize(self, *, source: str, payload: dict) -> dict:
        raise AssertionError("unchanged terms should not run LLM")


class ExistingTermsNoco:
    configured = True

    async def find_existing_record(self, target_table: str, ext_id: str) -> dict | None:
        assert target_table == "class101_terms"
        assert ext_id == "terms:refund"
        doc = extract_current_terms_document(
            html_text=make_terms_html(),
            slug="refund",
            title="환불정책",
            url="https://class101.net/ko/docs/terms/refund?viewMode=svod",
        )
        record = terms_to_record(
            doc=doc,
            collected_at=datetime(2026, 5, 14, 12, 0, tzinfo=KST),
            normalized={},
        )
        return {
            "Id": 10,
            "ext_id": ext_id,
            "source_hash": record.source_hash,
            "structured_sections": '[{"heading":"환불정책"}]',
        }


@pytest.mark.asyncio
async def test_terms_pipeline_collects_current_terms_document():
    records = await TermsPipeline(
        terms=FakeTermsClient(),
        llm=FakeLLM(),
        terms_configs=[
            {
                "slug": "refund",
                "title": "환불정책",
                "url": "https://class101.net/ko/docs/terms/refund?viewMode=svod",
            }
        ],
    ).collect(
        mode=PipelineMode.INCREMENTAL,
        limit=None,
        use_fixtures_when_unconfigured=False,
        collected_at=datetime(2026, 5, 14, 12, 0, tzinfo=KST),
    )

    assert len(records) == 1
    assert records[0].source_id == "terms:refund"
    assert records[0].normalized["llm_status"] == "fake"


@pytest.mark.asyncio
async def test_terms_pipeline_skips_llm_when_source_hash_unchanged():
    records = await TermsPipeline(
        terms=FakeTermsClient(),
        llm=FailOnLLM(),
        noco=ExistingTermsNoco(),
        terms_configs=[
            {
                "slug": "refund",
                "title": "환불정책",
                "url": "https://class101.net/ko/docs/terms/refund?viewMode=svod",
            }
        ],
    ).collect(
        mode=PipelineMode.INCREMENTAL,
        limit=None,
        use_fixtures_when_unconfigured=False,
        collected_at=datetime(2026, 5, 14, 12, 0, tzinfo=KST),
    )

    assert records == []
