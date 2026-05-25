import pytest

from kb_pipeline.models import PipelineMode
from kb_pipeline.pipelines.docbuilder_pipeline import DocBuilderPipeline


class FakeDocBuilder:
    configured = True
    graphql_configured = True

    async def fetch_document_table(self, *, first: int = 20, after: str | None = None) -> dict:
        assert first == 20
        assert after is None
        return {
            "edges": [
                {
                    "cursor": "cursor-known",
                    "node": {
                        "id": "doc-builder-existing-version",
                        "documentId": None,
                        "slug": "known-doc",
                        "title": "기존 독빌더 문서",
                        "version": 3,
                        "latestVersion": 3,
                        "isPublished": True,
                        "createdAt": "2026-05-10T01:00:00.000Z",
                        "publishedAt": "2026-05-11T02:57:00.000Z",
                        "hrefs": ["https://class101.net/ko/pages/known-doc"],
                        "imageUrls": ["https://cdn.class101.net/images/known-doc"],
                    }
                }
            ],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        }

    async def resolve_document_identity(self, id_or_slug: str) -> dict:
        assert id_or_slug == "known-doc"
        return {"documentId": "doc-builder-existing", "slug": "known-doc"}

    async def fetch_document_by_slug(self, slug: str) -> dict:
        assert slug == "known-doc"
        return {
            "id": "doc-builder-existing",
            "documentId": "doc-builder-existing",
            "slug": "known-doc",
            "title": "기존 독빌더 문서",
            "version": 3,
            "latestVersion": 3,
            "isPublished": True,
            "createdAt": "2026-05-10T01:00:00.000Z",
            "publishedAt": "2026-05-11T02:57:00.000Z",
            "hrefs": ["https://class101.net/ko/pages/known-doc"],
            "imageUrls": ["https://cdn.class101.net/images/known-doc"],
        }


class FailOnOCR:
    async def extract_from_url(self, image_url: str) -> str:
        raise AssertionError(f"unchanged doc_builder row should not run OCR: {image_url}")


class FailOnLLM:
    async def normalize(self, *, source: str, payload: dict) -> dict:
        raise AssertionError(f"unchanged doc_builder row should not run LLM: {source} {payload}")


class FakeNocoExistingMetadata:
    configured = True

    async def find_existing_record(self, target_table: str, ext_id: str) -> dict | None:
        assert target_table == "doc_builder"
        assert ext_id == "doc-builder-existing"
        return {
            "Id": 17,
            "ext_id": "doc-builder-existing",
            "source_updated_ts": "2026-05-11T02:57:00.000Z",
            "source_hash": "already-normalized",
        }


class FakeCollectDocBuilder(FakeDocBuilder):
    async def fetch_document_table(self, *, first: int = 20, after: str | None = None) -> dict:
        return {
            "edges": [
                {
                    "cursor": "cursor-new",
                    "node": {
                        "id": "doc-builder-new",
                        "documentId": None,
                        "slug": "new-doc",
                        "title": "신규 독빌더 문서",
                        "version": 5,
                        "latestVersion": 5,
                        "isPublished": True,
                        "isDeleted": False,
                        "createdAt": "2026-05-15T01:00:00.000Z",
                        "publishedAt": "2026-05-15T02:00:00.000Z",
                    },
                }
            ],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        }

    async def resolve_document_identity(self, id_or_slug: str) -> dict:
        assert id_or_slug == "new-doc"
        return {"documentId": "doc-builder-new", "slug": "new-doc"}

    async def fetch_document_by_slug(self, slug: str) -> dict:
        assert slug == "new-doc"
        return {
            "id": "doc-builder-new",
            "documentId": "doc-builder-new",
            "slug": "new-doc",
            "title": "신규 독빌더 문서",
            "version": 5,
            "latestVersion": 5,
            "isPublished": True,
            "isDeleted": False,
            "createdAt": "2026-05-15T01:00:00.000Z",
            "publishedAt": "2026-05-15T02:00:00.000Z",
            "hrefs": ["https://class101.net/ko/pages/new-doc"],
            "imageUrls": ["https://cdn.class101.net/images/new-doc"],
            "components": ["ImageBlock"],
        }


class FakeOCR:
    async def extract_from_url(self, image_url: str) -> str:
        assert image_url == "https://cdn.class101.net/images/new-doc"
        return "신규 독빌더 페이지 OCR 문구"


class FakeLLM:
    async def normalize(self, *, source: str, payload: dict) -> dict:
        assert source == "doc_builder"
        assert payload["title"] == "신규 독빌더 문서"
        assert "신규 독빌더 페이지 OCR 문구" in payload["ocr_text"]
        return {
            "summary": "신규 독빌더 문서 요약",
            "customer_answer": "신규 독빌더 문서는 현재 공개된 페이지입니다.",
        }


@pytest.mark.asyncio
async def test_docbuilder_pipeline_skips_ocr_and_llm_when_nocodb_metadata_unchanged():
    records = await DocBuilderPipeline(
        docbuilder=FakeDocBuilder(),
        ocr=FailOnOCR(),
        llm=FailOnLLM(),
        noco=FakeNocoExistingMetadata(),
    ).collect(
        mode=PipelineMode.INCREMENTAL,
        limit=1,
        use_fixtures_when_unconfigured=False,
    )

    assert records == []


@pytest.mark.asyncio
async def test_docbuilder_pipeline_collects_from_graphql_document_table():
    records = await DocBuilderPipeline(
        docbuilder=FakeCollectDocBuilder(),
        ocr=FakeOCR(),
        llm=FakeLLM(),
        noco=None,
    ).collect(
        mode=PipelineMode.INCREMENTAL,
        limit=1,
        use_fixtures_when_unconfigured=False,
    )

    assert len(records) == 1
    record = records[0]
    assert record.source_id == "doc-builder-new"
    assert record.target_table == "doc_builder"
    assert record.normalized["summary"] == "신규 독빌더 문서 요약"
    assert record.url == "https://class101.net/ko/pages/new-doc"
