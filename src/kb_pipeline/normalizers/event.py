from __future__ import annotations

from datetime import datetime
from typing import Any

from kb_pipeline.models import SourceRecord
from kb_pipeline.normalizers.common import build_source_hash, is_after_cutoff, to_kst


def include_event_content(event: dict[str, Any]) -> bool:
    if event.get("status") != "ACTIVE":
        return False
    started_at = event.get("startedAt")
    if not started_at:
        return False
    return is_after_cutoff(datetime.fromisoformat(started_at.replace("Z", "+00:00")))


def include_event_document(doc: dict[str, Any], *, since: datetime) -> bool:
    if doc.get("isPublished") is not True:
        return False
    if doc.get("isDeleted") is True:
        return False
    published_at = doc.get("publishedAt")
    if not published_at:
        return False
    published_at_dt = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
    return to_kst(published_at_dt) >= since


def event_to_record(
    *,
    event: dict[str, Any],
    collected_at: datetime,
    normalized: dict[str, Any] | None = None,
) -> SourceRecord | None:
    if not include_event_content(event):
        return None
    title = str(event.get("title") or event.get("id") or "event_promotion")
    source_hash = build_source_hash(event)
    return SourceRecord(
        source="event_promotion",
        source_id=str(event["id"]),
        target_table="event_promotion",
        title=title,
        raw=event,
        normalized=normalized or {"summary": title, "status": event.get("status")},
        source_updated_ts=event.get("updatedAt") or event.get("startedAt"),
        source_hash=source_hash,
        last_collected_at=collected_at.isoformat(),
        url=(event.get("quickMenus") or [{}])[0].get("link"),
    )


def event_document_to_record(
    *,
    doc: dict[str, Any],
    ocr_text: str,
    collected_at: datetime,
    normalized: dict[str, Any] | None = None,
) -> SourceRecord | None:
    if doc.get("isPublished") is not True or doc.get("isDeleted") is True:
        return None
    source_id = event_document_source_id(doc)
    if not source_id:
        return None
    slug = str(doc.get("slug") or "").strip()
    title = str(doc.get("title") or slug or source_id)
    url = str(doc.get("url") or (f"https://class101.net/ko/pages/{slug}" if slug else ""))
    hash_payload = {
        "documentId": source_id,
        "slug": slug,
        "version": doc.get("version"),
        "latestVersion": doc.get("latestVersion"),
        "publishedAt": doc.get("publishedAt"),
        "hrefs": doc.get("hrefs") or [],
        "imageUrls": doc.get("imageUrls") or [],
        "ocr": ocr_text,
    }
    raw = {k: v for k, v in doc.items() if k not in {"content", "dsl", "transpiledContent"}}
    raw["source_kind"] = "doc_builder_document"
    raw["ocr_text"] = ocr_text
    return SourceRecord(
        source="event_promotion",
        source_id=source_id,
        target_table="event_promotion",
        title=title,
        raw=raw,
        normalized=normalized or {"summary": title, "ocr_text": ocr_text[:5000]},
        source_updated_ts=doc.get("publishedAt") or doc.get("createdAt"),
        source_hash=build_source_hash(hash_payload),
        last_collected_at=collected_at.isoformat(),
        url=url or None,
    )


def event_document_source_id(doc: dict[str, Any]) -> str:
    slug = str(doc.get("slug") or "").strip()
    if slug:
        return f"doc_builder:{slug}"
    return str(doc.get("documentId") or doc.get("id") or "").strip()
