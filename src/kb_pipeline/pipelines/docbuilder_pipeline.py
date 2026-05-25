from __future__ import annotations

import asyncio
from datetime import datetime

from kb_pipeline.clients.docbuilder import DocBuilderClient
from kb_pipeline.clients.llm import LLMClient
from kb_pipeline.clients.ocr import OCRClient
from kb_pipeline.config import COLLECTION_CUTOFF
from kb_pipeline.fixtures import collected_at_sample, sample_doc_builder_document
from kb_pipeline.models import PipelineMode, SourceRecord
from kb_pipeline.normalizers.docbuilder import (
    doc_builder_to_record,
    include_doc_builder_document,
)


class DocBuilderPipeline:
    def __init__(
        self,
        *,
        docbuilder: DocBuilderClient,
        ocr: OCRClient,
        llm: LLMClient,
        noco: object | None = None,
        state: object | None = None,
    ) -> None:
        self.docbuilder = docbuilder
        self.ocr = ocr
        self.llm = llm
        self.noco = noco
        self.state = state

    async def collect(
        self,
        *,
        mode: PipelineMode,
        limit: int | None,
        use_fixtures_when_unconfigured: bool,
    ) -> list[SourceRecord]:
        if self.docbuilder.configured or getattr(self.docbuilder, "graphql_configured", False):
            return await self._collect_live(mode=mode, limit=limit)
        if use_fixtures_when_unconfigured:
            return await self._collect_fixtures()
        return []

    async def _collect_fixtures(self) -> list[SourceRecord]:
        doc, ocr_text = sample_doc_builder_document()
        normalized = await self.llm.normalize(
            source="doc_builder",
            payload={
                "title": doc["title"],
                "ocr_text": ocr_text,
                "body": ocr_text,
                "links": doc.get("hrefs", []),
            },
        )
        record = doc_builder_to_record(
            doc=doc,
            ocr_text=ocr_text,
            collected_at=collected_at_sample(),
            normalized=normalized,
        )
        return [record] if record else []

    async def _collect_live(self, *, mode: PipelineMode, limit: int | None) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        after: str | None = None
        first = 20
        while True:
            page = await self.docbuilder.fetch_document_table(first=first, after=after)
            edges = page.get("edges", [])
            for edge in edges:
                summary_doc = edge.get("node") or {}
                if not include_doc_builder_document(summary_doc):
                    continue
                slug = str(summary_doc.get("slug") or "").strip()
                if not slug:
                    continue
                summary_doc = await self._with_resolved_identity(summary_doc, slug)
                if await self._metadata_unchanged(summary_doc):
                    continue
                try:
                    detail_doc = await self.docbuilder.fetch_document_by_slug(slug)
                except Exception as exc:  # noqa: BLE001
                    detail_doc = {"load_error": f"{type(exc).__name__}: {exc}"}
                doc = {**summary_doc, **detail_doc}
                for key in ("id", "createdAt", "publishedAt", "isDeleted"):
                    if summary_doc.get(key) is not None:
                        doc[key] = summary_doc[key]
                if not doc.get("documentId"):
                    doc["documentId"] = summary_doc.get("documentId") or summary_doc.get("id")
                doc["url"] = f"https://class101.net/ko/pages/{slug}"
                ocr_text = await self._extract_ocr_text(doc)
                normalized = await self.llm.normalize(
                    source="doc_builder",
                    payload={
                        "title": doc.get("title"),
                        "ocr_text": ocr_text,
                        "body": "\n".join(
                            str(item)
                            for item in doc.get("textSnippets", [])
                            if str(item or "").strip()
                        )
                        or ocr_text,
                        "links": doc.get("hrefs", []),
                        "components": doc.get("components", []),
                        "document": {
                            "documentId": doc.get("documentId") or doc.get("id"),
                            "slug": doc.get("slug"),
                            "title": doc.get("title"),
                            "version": doc.get("version"),
                            "latestVersion": doc.get("latestVersion"),
                            "publishedAt": doc.get("publishedAt"),
                            "url": doc.get("url"),
                        },
                        "mode": mode.value,
                    },
                )
                record = doc_builder_to_record(
                    doc=doc,
                    ocr_text=ocr_text,
                    collected_at=datetime.now(tz=COLLECTION_CUTOFF.tzinfo),
                    normalized=normalized,
                )
                if record:
                    records.append(record)
                if limit and len(records) >= limit:
                    return records
            page_info = page.get("pageInfo") or {}
            if (
                not page_info.get("hasNextPage")
                or not edges
                or self._page_is_before_collection_cutoff(edges)
            ):
                break
            after = page_info.get("endCursor")
        return records

    async def _metadata_unchanged(self, doc: dict[str, object]) -> bool:
        if not self.noco or not getattr(self.noco, "configured", False):
            return False
        source_id = str(doc.get("documentId") or doc.get("id") or "").strip()
        source_updated_ts = str(
            doc.get("publishedAt") or doc.get("updatedAt") or doc.get("createdAt") or ""
        ).strip()
        if not source_id or not source_updated_ts:
            return False
        try:
            existing = await self.noco.find_existing_record("doc_builder", source_id)
        except Exception:  # noqa: BLE001
            return False
        if not existing:
            state_payload = self._state_payload(source_id)
            if not state_payload:
                return False
            return str(state_payload.get("source_updated_ts") or "").strip() == source_updated_ts
        return str(existing.get("source_updated_ts") or "").strip() == source_updated_ts

    async def _extract_ocr_text(self, doc: dict[str, object]) -> str:
        image_urls = doc.get("imageUrls") or []
        if not isinstance(image_urls, list):
            return ""
        chunks: list[str] = []
        for image_url in image_urls[:2]:
            try:
                chunks.append(
                    await asyncio.wait_for(
                        self.ocr.extract_from_url(str(image_url)),
                        timeout=30,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                chunks.append(f"[OCR_FAILED: {type(exc).__name__}]")
        return "\n".join(chunk for chunk in chunks if chunk)

    def _page_is_before_collection_cutoff(self, edges: list[dict[str, object]]) -> bool:
        if not edges:
            return True
        last = edges[-1].get("node") if isinstance(edges[-1], dict) else None
        if not isinstance(last, dict):
            return False
        source_date = str(last.get("createdAt") or last.get("publishedAt") or "").strip()
        if not source_date:
            return False
        try:
            parsed = datetime.fromisoformat(source_date.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed.astimezone(COLLECTION_CUTOFF.tzinfo) < COLLECTION_CUTOFF

    def _state_payload(self, source_id: str) -> dict[str, object] | None:
        getter = getattr(self.state, "get_source_payload", None)
        if not getter:
            return None
        try:
            payload = getter(source_id)
        except Exception:  # noqa: BLE001
            return None
        return payload if isinstance(payload, dict) else None

    async def _with_resolved_identity(
        self,
        summary_doc: dict[str, object],
        slug: str,
    ) -> dict[str, object]:
        resolver = getattr(self.docbuilder, "resolve_document_identity", None)
        if not resolver:
            return summary_doc
        try:
            identity = await resolver(slug)
        except Exception:  # noqa: BLE001
            return summary_doc
        if not isinstance(identity, dict):
            return summary_doc
        resolved = {**summary_doc}
        if identity.get("documentId"):
            resolved["documentId"] = identity["documentId"]
        if identity.get("slug"):
            resolved["slug"] = identity["slug"]
        return resolved
