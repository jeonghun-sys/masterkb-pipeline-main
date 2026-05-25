from __future__ import annotations

from datetime import datetime
from typing import Any

from kb_pipeline.models import SourceRecord
from kb_pipeline.normalizers.common import build_source_hash, is_after_cutoff


def include_doc_builder_document(doc: dict[str, Any]) -> bool:
    if doc.get("isPublished") is not True:
        return False
    source_date = doc.get("publishedAt") or doc.get("createdAt") or doc.get("updatedAt")
    if not source_date:
        return False
    return is_after_cutoff(datetime.fromisoformat(source_date.replace("Z", "+00:00")))


def doc_builder_to_record(
    *,
    doc: dict[str, Any],
    ocr_text: str,
    collected_at: datetime,
    normalized: dict[str, Any] | None = None,
) -> SourceRecord | None:
    if not include_doc_builder_document(doc):
        return None
    source_id = str(doc.get("documentId") or doc.get("id"))
    title = str(doc.get("title") or doc.get("slug") or source_id)
    hash_payload = {
        "documentId": source_id,
        "version": doc.get("version") or doc.get("latestVersion"),
        "publishedAt": doc.get("publishedAt"),
        "text": doc.get("text") or doc.get("contentSummary"),
        "ocr": ocr_text,
        "links": doc.get("hrefs") or [],
    }
    return SourceRecord(
        source="doc_builder",
        source_id=source_id,
        target_table="doc_builder",
        title=title,
        raw={k: v for k, v in doc.items() if k not in {"content", "dsl"}},
        normalized=normalized or {"summary": title, "ocr_text": ocr_text[:5000]},
        source_updated_ts=doc.get("publishedAt") or doc.get("updatedAt") or doc.get("createdAt"),
        source_hash=build_source_hash(hash_payload),
        last_collected_at=collected_at.isoformat(),
        url=doc.get("url"),
    )

