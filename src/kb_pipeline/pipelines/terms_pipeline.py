from __future__ import annotations

from datetime import datetime

from kb_pipeline.clients.llm import LLMClient
from kb_pipeline.clients.terms import TermsClient
from kb_pipeline.config import COLLECTION_CUTOFF, TERMS, TermsConfig
from kb_pipeline.fixtures import collected_at_sample
from kb_pipeline.models import PipelineMode, SourceRecord
from kb_pipeline.normalizers.terms import extract_current_terms_document, terms_to_record


class TermsPipeline:
    def __init__(
        self,
        *,
        terms: TermsClient,
        llm: LLMClient,
        noco: object | None = None,
        terms_configs: list[TermsConfig | dict[str, str]] | None = None,
    ) -> None:
        self.terms = terms
        self.llm = llm
        self.noco = noco
        self.terms_configs = terms_configs or TERMS

    async def collect(
        self,
        *,
        mode: PipelineMode,
        limit: int | None,
        use_fixtures_when_unconfigured: bool,
        collected_at: datetime | None = None,
    ) -> list[SourceRecord]:
        if mode == PipelineMode.SMOKE and use_fixtures_when_unconfigured:
            return await self._collect_fixtures()
        return await self._collect_live(
            limit=limit,
            collected_at=collected_at or datetime.now(tz=COLLECTION_CUTOFF.tzinfo),
        )

    async def _collect_fixtures(self) -> list[SourceRecord]:
        doc = {
            "slug": "refund",
            "title": "환불정책",
            "url": "https://class101.net/ko/docs/terms/refund?viewMode=svod",
            "version_id": "fixture",
            "version": "2026-04-19",
            "effectiveFrom": "2026-04-19T15:00:00.000Z",
            "content_html": "<h1>환불정책</h1><p>구독 상품은 조건에 따라 환불됩니다.</p>",
            "content_text": "환불정책\n구독 상품은 조건에 따라 환불됩니다.",
            "sections": [
                {
                    "heading": "환불정책",
                    "level": 1,
                    "items": ["구독 상품은 조건에 따라 환불됩니다."],
                }
            ],
            "section_markdown": "## 환불정책\n구독 상품은 조건에 따라 환불됩니다.",
        }
        normalized = await self.llm.normalize(
            source="class101_terms",
            payload={
                "terms_key": doc["slug"],
                "title": doc["title"],
                "version": doc["version"],
                "effective_from": doc["effectiveFrom"],
                "body": doc["content_text"],
            },
        )
        return [
            terms_to_record(
                doc=doc,
                collected_at=collected_at_sample(),
                normalized=normalized,
            )
        ]

    async def _collect_live(
        self,
        *,
        limit: int | None,
        collected_at: datetime,
    ) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        for config in self.terms_configs:
            item = _terms_config_dict(config)
            html_text = await self.terms.fetch(item["url"])
            doc = extract_current_terms_document(
                html_text=html_text,
                slug=item["slug"],
                title=item["title"],
                url=item["url"],
            )
            probe = terms_to_record(doc=doc, collected_at=collected_at, normalized={})
            if await self._source_hash_unchanged(probe):
                continue
            normalized = await self.llm.normalize(
                source="class101_terms",
                payload={
                    "terms_key": doc["slug"],
                    "title": doc["title"],
                    "version": doc["version"],
                    "effective_from": doc["effectiveFrom"],
                    "url": doc["url"],
                    "body": doc["content_text"],
                },
            )
            records.append(
                terms_to_record(
                    doc=doc,
                    collected_at=collected_at,
                    normalized=normalized,
                )
            )
            if limit and len(records) >= limit:
                break
        return records

    async def _source_hash_unchanged(self, record: SourceRecord) -> bool:
        if not self.noco or not getattr(self.noco, "configured", False):
            return False
        try:
            existing = await self.noco.find_existing_record(
                record.target_table,
                record.source_id,
            )
        except Exception:  # noqa: BLE001
            return False
        if not existing:
            return False
        if not existing.get("structured_sections"):
            return False
        return str(existing.get("source_hash") or "").strip() == record.source_hash


def _terms_config_dict(config: TermsConfig | dict[str, str]) -> dict[str, str]:
    if isinstance(config, dict):
        return config
    return {
        "slug": config.slug,
        "title": config.title,
        "url": config.url,
    }
