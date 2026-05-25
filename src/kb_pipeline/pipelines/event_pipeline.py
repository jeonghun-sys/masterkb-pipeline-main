from __future__ import annotations

from datetime import datetime, timedelta

from kb_pipeline.clients.docbuilder import DocBuilderClient
from kb_pipeline.clients.event import EventClient
from kb_pipeline.clients.llm import LLMClient
from kb_pipeline.clients.ocr import OCRClient
from kb_pipeline.config import COLLECTION_CUTOFF
from kb_pipeline.fixtures import collected_at_sample, sample_event_content
from kb_pipeline.models import PipelineMode, SourceRecord
from kb_pipeline.normalizers.event import (
    event_document_source_id,
    event_document_to_record,
    event_to_record,
    include_event_content,
    include_event_document,
)


class EventPipeline:
    def __init__(
        self,
        *,
        llm: LLMClient,
        event_client: EventClient | None = None,
        docbuilder: DocBuilderClient | None = None,
        ocr: OCRClient | None = None,
        noco: object | None = None,
    ) -> None:
        self.event_client = event_client
        self.docbuilder = docbuilder
        self.ocr = ocr
        self.llm = llm
        self.noco = noco

    async def collect(
        self,
        *,
        mode: PipelineMode,
        limit: int | None,
        use_fixtures_when_unconfigured: bool,
        now: datetime | None = None,
    ) -> list[SourceRecord]:
        if self._docbuilder_configured:
            return await self._collect_docbuilder_live(
                mode=mode,
                limit=limit,
                now=now or datetime.now(tz=COLLECTION_CUTOFF.tzinfo),
            )
        if self.event_client and self.event_client.configured:
            return await self._collect_live(mode=mode, limit=limit)
        if use_fixtures_when_unconfigured:
            return await self._collect_fixtures()
        return []

    @property
    def _docbuilder_configured(self) -> bool:
        if not self.docbuilder:
            return False
        return bool(
            getattr(self.docbuilder, "graphql_configured", None)
            or getattr(self.docbuilder, "configured", False)
        )

    async def _collect_fixtures(self) -> list[SourceRecord]:
        event = sample_event_content()
        normalized = await self.llm.normalize(
            source="event_promotion",
            payload={
                "title": event["title"],
                "status": event["status"],
                "body": (
                    f"기간: {event['startedAt']} ~ {event['endedAt']}. "
                    f"링크: {event['quickMenus'][0]['link']}"
                ),
            },
        )
        record = event_to_record(
            event=event,
            collected_at=collected_at_sample(),
            normalized=normalized,
        )
        return [record] if record else []

    async def _collect_live(self, *, mode: PipelineMode, limit: int | None) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        offset = 0
        page_limit = 50
        while True:
            page = await self.event_client.fetch_event_contents(offset=offset, limit=page_limit)
            edges = page.get("edges", [])
            for edge in edges:
                event = edge.get("node") or {}
                if not include_event_content(event):
                    continue
                normalized = await self.llm.normalize(
                    source="event_promotion",
                    payload={
                        "title": event.get("title"),
                        "status": event.get("status"),
                        "body": (
                            f"기간: {event.get('startedAt')} ~ {event.get('endedAt')}. "
                            f"promotionId: {event.get('promotionId')}. mode={mode.value}"
                        ),
                    },
                )
                record = event_to_record(
                    event=event,
                    collected_at=datetime.now(tz=COLLECTION_CUTOFF.tzinfo),
                    normalized=normalized,
                )
                if record:
                    records.append(record)
                if limit and len(records) >= limit:
                    return records
            offset += page_limit
            total = int(page.get("totalCount") or 0)
            if offset >= total or not edges:
                break
        return records

    async def _collect_docbuilder_live(
        self,
        *,
        mode: PipelineMode,
        limit: int | None,
        now: datetime,
    ) -> list[SourceRecord]:
        if not self.docbuilder or not self.ocr:
            return []
        records: list[SourceRecord] = []
        since = COLLECTION_CUTOFF if mode == PipelineMode.BACKFILL else now - timedelta(days=14)
        after: str | None = None
        first = 20
        while True:
            page = await self.docbuilder.fetch_document_table(first=first, after=after)
            edges = page.get("edges", [])
            for edge in edges:
                summary_doc = edge.get("node") or {}
                if not include_event_document(summary_doc, since=since):
                    continue
                slug = str(summary_doc.get("slug") or "").strip()
                if not slug:
                    continue
                if await self._docbuilder_metadata_unchanged(summary_doc):
                    continue
                detail_doc = await self.docbuilder.fetch_document_by_slug(slug)
                doc = {**detail_doc, **summary_doc}
                doc["url"] = f"https://class101.net/ko/pages/{slug}"
                ocr_text = await self._extract_ocr_text(doc)
                normalized = await self.llm.normalize(
                    source="event_promotion",
                    payload={
                        "document": {
                            "documentId": doc.get("documentId") or doc.get("id"),
                            "slug": doc.get("slug"),
                            "title": doc.get("title"),
                            "version": doc.get("version"),
                            "latestVersion": doc.get("latestVersion"),
                            "publishedAt": doc.get("publishedAt"),
                            "url": doc.get("url"),
                        },
                        "ocr_text": ocr_text,
                        "links": doc.get("hrefs", []),
                        "imageUrls": doc.get("imageUrls", []),
                        "components": doc.get("components", []),
                        "mode": mode.value,
                    },
                )
                record = event_document_to_record(
                    doc=doc,
                    ocr_text=ocr_text,
                    collected_at=now,
                    normalized=normalized,
                )
                if record:
                    records.append(record)
                if limit and len(records) >= limit:
                    return records
            page_info = page.get("pageInfo") or {}
            if not page_info.get("hasNextPage") or not edges:
                break
            after = page_info.get("endCursor")
        return records

    async def _docbuilder_metadata_unchanged(self, summary_doc: dict[str, object]) -> bool:
        if not self.noco or not getattr(self.noco, "configured", False):
            return False
        source_id = event_document_source_id(summary_doc)
        source_updated_ts = str(
            summary_doc.get("publishedAt") or summary_doc.get("createdAt") or ""
        ).strip()
        if not source_id or not source_updated_ts:
            return False
        try:
            existing = await self.noco.find_existing_record("event_promotion", source_id)
        except Exception:  # noqa: BLE001
            return False
        if not existing:
            return False
        return str(existing.get("source_updated_ts") or "").strip() == source_updated_ts

    async def _extract_ocr_text(self, doc: dict[str, object]) -> str:
        if not self.ocr:
            return ""
        image_urls = doc.get("imageUrls") or []
        if not isinstance(image_urls, list):
            return ""
        chunks: list[str] = []
        for image_url in image_urls[:5]:
            try:
                chunks.append(await self.ocr.extract_from_url(str(image_url)))
            except Exception as exc:  # noqa: BLE001
                chunks.append(f"[OCR_FAILED: {type(exc).__name__}]")
        return "\n".join(chunk for chunk in chunks if chunk)
