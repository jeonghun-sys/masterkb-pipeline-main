from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import httpx

from kb_pipeline.config import NOCO_TABLE_IDS
from kb_pipeline.merge import (
    MergeDecision,
    canonical_hash_for,
    knowledge_unit_key,
    merge_metadata,
    parse_source_refs,
)
from kb_pipeline.models import SourceRecord
from kb_pipeline.normalizers.common import to_kst


def _compact(value: object, limit: int = 4000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 18].rstrip() + " [일부 생략]"


def _join_changes(value: object) -> str:
    if isinstance(value, list):
        return " / ".join(_compact(item, 300) for item in value if str(item or "").strip())
    return _compact(value, 1200)


def _tags(*values: object) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, list):
            candidates = value
        else:
            candidates = [value]
        for candidate in candidates:
            text = _compact(candidate, 80)
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
    return out


def _slack_ts(record: SourceRecord) -> str:
    if record.thread_ref and ":" in record.thread_ref:
        return record.thread_ref.split(":", 1)[1]
    return record.source_updated_ts or ""


def _source_channel(record: SourceRecord) -> str:
    channel = record.raw.get("channel")
    return str(channel or "")


def _clean_slack_markup(text: object) -> str:
    value = str(text or "")
    value = re.sub(r"<@[^>]+>", "", value)
    value = re.sub(r"<!subteam\^[^>]+>", "", value)
    value = re.sub(r"<!channel>", "", value)
    value = re.sub(r"<([^|>]+)\|([^>]+)>", r"\2", value)
    value = re.sub(r"<(https?://[^>]+)>", r"\1", value)
    value = re.sub(r":[a-zA-Z0-9_+\-]+:", "", value)
    value = value.replace("*", "").replace("_", "")
    value = re.sub(r"\bcc\.", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -•\n\t")


def _parent_text(record: SourceRecord) -> str:
    parent = record.raw.get("parent")
    if isinstance(parent, dict):
        return str(parent.get("text") or "")
    return ""


def _slack_title(record: SourceRecord) -> str:
    text = _parent_text(record)
    normalized = record.normalized
    category = _compact(normalized.get("category"), 80)
    intent = _compact(normalized.get("intent"), 80)
    labels: list[str] = []
    for match in re.findall(r"\[([^\]]{2,80})\]", text):
        label = _clean_slack_markup(match)
        if label:
            labels.append(label)
    if labels:
        title = labels[0]
        if intent and intent not in title:
            title = f"{title} / {intent}"
        return title[:180]

    for line in text.splitlines():
        candidate = _clean_slack_markup(line)
        if _is_weak_slack_title(candidate):
            continue
        linear_title = _linear_issue_title(candidate)
        if linear_title:
            return linear_title[:180]
        if candidate:
            return candidate[:180]

    fallback = _clean_slack_markup(record.title)
    if fallback and not _is_weak_slack_title(fallback):
        return fallback[:180]
    if category and intent:
        return f"{category} / {intent}"[:180]
    if intent:
        return intent[:180]
    if category:
        return category[:180]
    summary = _compact(normalized.get("summary"), 180)
    if summary:
        return summary[:180]
    return _compact(normalized.get("category") or record.target_table, 180)


def _is_weak_slack_title(title: str) -> bool:
    normalized = title.strip()
    if not normalized:
        return True
    if normalized in {"안녕하세요", "안녕하세요!", "안녕하세요.", "안녕하세요!!"}:
        return True
    if re.fullmatch(r"(cc\.?\s*)+", normalized, flags=re.IGNORECASE):
        return True
    return False


def _linear_issue_title(title: str) -> str:
    if "linear.app" not in title and "created a" not in title:
        return ""
    match = re.search(r"(PRDT-\d+)\s*/?\s*(.+)$", title)
    if match:
        return f"{match.group(1)} {match.group(2)}"
    match = re.search(r"created a\s+(.+)$", title)
    return match.group(1).strip() if match else ""


def _slack_thread_markdown(record: SourceRecord, limit: int = 12000) -> str:
    lines: list[str] = []
    parent_text = _clean_slack_markup(_parent_text(record))
    if parent_text:
        lines.extend(["## Parent", parent_text])
    replies = record.raw.get("replies")
    if isinstance(replies, list) and replies:
        lines.append("## Replies")
        for reply in replies:
            if not isinstance(reply, dict):
                continue
            text = _clean_slack_markup(reply.get("text"))
            if text:
                lines.append(f"- {text}")
    return "\n".join(lines)[:limit]


def _raw_thread_meta(record: SourceRecord) -> dict[str, Any]:
    parent = record.raw.get("parent")
    replies = record.raw.get("replies")
    parent_obj = parent if isinstance(parent, dict) else {}
    return {
        "channel": _source_channel(record),
        "thread_ref": record.thread_ref,
        "parent_ts": parent_obj.get("ts") or record.source_updated_ts,
        "parent_user": parent_obj.get("user") or parent_obj.get("username") or "",
        "reply_count": record.source_reply_count,
        "latest_reply": record.source_latest_reply_ts,
        "reply_text_preview": [
            _clean_slack_markup(reply.get("text"))
            for reply in replies[:20]
            if isinstance(reply, dict) and _clean_slack_markup(reply.get("text"))
        ]
        if isinstance(replies, list)
        else [],
    }


def _tracking_payload(record: SourceRecord) -> dict[str, Any]:
    return {
        "source_updated_ts": record.source_updated_ts,
        "source_latest_reply_ts": record.source_latest_reply_ts,
        "source_reply_count": record.source_reply_count,
        "source_hash": record.source_hash,
        "last_collected_at": record.last_collected_at,
    }


def _merge_tracking_payload(record: SourceRecord) -> dict[str, Any]:
    return merge_metadata(
        record,
        status=str(record.normalized.get("merge_status") or "standalone"),
    )


def _normalized_summary(record: SourceRecord) -> str:
    return _compact(record.normalized.get("summary"), 3000)


def _customer_answer(record: SourceRecord) -> str:
    answer = _compact(record.normalized.get("customer_answer"), 3000)
    if len(answer) < 12:
        return _normalized_summary(record)
    return answer


def _search_text(record: SourceRecord, *, title: str) -> str:
    normalized = record.normalized
    return _compact(
        " ".join(
            [
                title,
                _source_channel(record),
                _compact(normalized.get("category")),
                _compact(normalized.get("intent")),
                _normalized_summary(record),
                _customer_answer(record),
                _join_changes(normalized.get("changes")),
            ]
        ),
        12000,
    )


def _slack_base_payload(record: SourceRecord) -> dict[str, Any]:
    title = _slack_title(record)
    normalized = record.normalized
    return {
        "Title": title,
        "ext_id": record.source_id,
        "source_channel": _source_channel(record),
        "slack_ts": _slack_ts(record),
        "url": record.url or "",
        "status": True,
        "tags": _tags(
            record.target_table,
            _source_channel(record),
            normalized.get("category"),
            normalized.get("intent"),
        ),
        **_tracking_payload(record),
        **_merge_tracking_payload(record),
    }


def _slack_cs_payload(record: SourceRecord) -> dict[str, Any]:
    title = _slack_title(record)
    normalized = record.normalized
    summary = _normalized_summary(record)
    answer = _customer_answer(record)
    changes = _join_changes(normalized.get("changes"))
    content = "\n\n".join(
        part
        for part in [
            f"## 요약\n{summary}" if summary else "",
            f"## 고객 안내\n{answer}" if answer else "",
            f"## 내부 참고\n{changes}" if changes else "",
        ]
        if part
    )
    return {
        **_slack_base_payload(record),
        "Title": title,
        "content_type": "slack_cs_data",
        "category": _compact(normalized.get("category"), 120),
        "inquiry": summary,
        "resolution": answer,
        "content": content,
        "search_text": _search_text(record, title=title),
    }


def _changelog_payload(record: SourceRecord) -> dict[str, Any]:
    normalized = record.normalized
    title = _slack_title(record)
    changes = _join_changes(normalized.get("changes"))
    return {
        **_slack_base_payload(record),
        "Title": title,
        "summary": _normalized_summary(record),
        "impact_area": _compact(normalized.get("category"), 120),
        "impact_summary": changes,
        "change_type": _compact(normalized.get("intent"), 120),
        "action_required": _compact(
            normalized.get("internal_note") or normalized.get("customer_answer") or changes,
            2000,
        ),
        "noise_removed": int(normalized.get("noise_removed") or 0),
        "refined_data": normalized,
        "raw_data": _raw_thread_meta(record),
        "raw_thread_md": _slack_thread_markdown(record),
        "thread_ref": record.thread_ref or "",
        "collected_at": record.last_collected_at,
    }


def _promotion_payload(record: SourceRecord) -> dict[str, Any]:
    normalized = record.normalized
    title = _slack_title(record)
    changes = _join_changes(normalized.get("changes"))
    return {
        **_slack_base_payload(record),
        "Title": title,
        "summary": _normalized_summary(record),
        "customer_answer": _customer_answer(record),
        "benefit_summary": _normalized_summary(record),
        "condition_summary": changes,
        "promotion_type": _compact(normalized.get("category"), 120),
        "target_audience": _compact(normalized.get("intent"), 120),
        "noise_removed": int(normalized.get("noise_removed") or 0),
        "refined_data": normalized,
        "raw_data": _raw_thread_meta(record),
        "raw_thread_md": _slack_thread_markdown(record),
        "thread_ref": record.thread_ref or "",
        "collected_at": record.last_collected_at,
    }


def _product_issue_payload(record: SourceRecord) -> dict[str, Any]:
    title = _slack_title(record)
    normalized = record.normalized
    return {
        **_slack_base_payload(record),
        "Title": title,
        "content_type": "product_issue",
        "issue": _normalized_summary(record),
        "solution": _customer_answer(record),
        "content": _search_text(record, title=title),
        "owner_team": _compact(normalized.get("category"), 120),
    }


def _date_kst(iso_value: object) -> str:
    if not iso_value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
        return to_kst(parsed).date().isoformat()
    except ValueError:
        return ""


def _event_payload(record: SourceRecord) -> dict[str, Any]:
    raw = record.raw
    summary = _normalized_summary(record)
    quick_menu_links = [
        item.get("link") for item in raw.get("quickMenus", []) if isinstance(item, dict)
    ]
    doc_links = raw.get("hrefs") if isinstance(raw.get("hrefs"), list) else []
    links = [*quick_menu_links, *doc_links]
    if record.url:
        links.append(record.url)
    title = _compact(record.title, 180)
    is_doc_builder_document = raw.get("source_kind") == "doc_builder_document"
    source_label = (
        "DocBuilder Document" if is_doc_builder_document else "CLASS101 Admin EventContent"
    )
    ocr_text = _compact(raw.get("ocr_text"), 3000)
    body_md = "\n".join(
        [
            f"# {title}",
            "",
            "## 요약",
            summary,
            "",
            "## 문서 정보",
            f"- Source: {source_label}",
            f"- Published At: {_date_kst(raw.get('publishedAt')) or '-'}",
            f"- Version: {raw.get('version') or '-'} / Latest: {raw.get('latestVersion') or '-'}",
            "",
            "## 기간",
            f"- 시작: {_date_kst(raw.get('startedAt')) or '-'}",
            f"- 종료: {_date_kst(raw.get('endedAt')) or '-'}",
            "",
            "## 링크",
            "\n".join(f"- {link}" for link in links if link) or "- 없음",
            "",
            "## OCR",
            ocr_text or "- 없음",
        ]
    )
    payload = {
        "Title": title,
        "ext_id": record.source_id,
        "content_type": "event_promotion",
        "workflow_answer": summary,
        "body_md": body_md,
        "search_body": _compact(
            " ".join(
                [
                    title,
                    summary,
                    str(raw.get("status") or ""),
                    str(raw.get("promotionId") or ""),
                    " ".join(str(link) for link in links if link),
                    ocr_text,
                ]
            ),
            12000,
        ),
        "status": True if is_doc_builder_document else raw.get("status") == "ACTIVE",
        "tags": _tags(
            "event_promotion",
            "doc_builder_document" if is_doc_builder_document else raw.get("status"),
            "published" if raw.get("isPublished") is True else None,
            record.normalized.get("category"),
        ),
        "thread_ref": record.thread_ref or "",
        "url": record.url or "",
        **_tracking_payload(record),
        **_merge_tracking_payload(record),
    }
    optional_fields = {
        "event_start_date": _date_kst(raw.get("startedAt")),
        "event_end_date": _date_kst(raw.get("endedAt")),
        "origin_created_at": raw.get("startedAt"),
        "origin_updated_at": record.source_updated_ts,
    }
    payload.update({key: value for key, value in optional_fields.items() if value})
    return payload


def _doc_builder_payload(record: SourceRecord) -> dict[str, Any]:
    raw = record.raw
    title = _compact(record.title, 180)
    summary = _normalized_summary(record)
    return {
        "Title": title,
        "ext_id": record.source_id,
        "content_type": "doc_builder",
        "content": "\n\n".join(
            part
            for part in [
                f"## 요약\n{summary}" if summary else "",
                f"## 고객 안내\n{_customer_answer(record)}",
                "## 주요 링크\n"
                + "\n".join(f"- {link}" for link in raw.get("hrefs", [])[:20]),
            ]
            if part
        ),
        "workflow_response": {
            **record.normalized,
            "documentId": raw.get("documentId"),
            "slug": raw.get("slug"),
            "version": raw.get("version"),
            "latestVersion": raw.get("latestVersion"),
            "components": raw.get("components", []),
            "imageUrlCount": len(raw.get("imageUrls", [])),
        },
        "search_text": _compact(
            " ".join(
                [
                    title,
                    summary,
                    _customer_answer(record),
                    " ".join(raw.get("components", [])),
                    " ".join(raw.get("hrefs", [])[:20]),
                ]
            ),
            12000,
        ),
        "status": raw.get("isPublished") is True,
        "tags": _tags("doc_builder", record.normalized.get("category"), raw.get("components", [])),
        "created_at": raw.get("createdAt") or "",
        "updated_at": raw.get("updatedAt") or record.source_updated_ts or "",
        "url": record.url or "",
        **_tracking_payload(record),
        **_merge_tracking_payload(record),
    }


def _terms_payload(record: SourceRecord) -> dict[str, Any]:
    raw = record.raw
    title = _compact(record.title, 180)
    summary = _normalized_summary(record)
    answer = _customer_answer(record)
    content = str(raw.get("section_markdown") or raw.get("content_text") or "")[:90000]
    sections = raw.get("sections") if isinstance(raw.get("sections"), list) else []
    return {
        "Title": title,
        "ext_id": record.source_id,
        "content_type": "class101_terms",
        "terms_key": _compact(raw.get("slug"), 120),
        "version": _compact(raw.get("version"), 120),
        "version_id": _compact(raw.get("version_id"), 120),
        "effective_from": raw.get("effectiveFrom") or "",
        "summary": summary,
        "customer_answer": answer,
        "content": content,
        "structured_sections": json.dumps(sections, ensure_ascii=False),
        "section_count": len(sections),
        "workflow_response": json.dumps(
            {**record.normalized, "sections": sections},
            ensure_ascii=False,
        ),
        "raw_data": json.dumps(
            {
                "slug": raw.get("slug"),
                "version_id": raw.get("version_id"),
                "version": raw.get("version"),
                "effectiveFrom": raw.get("effectiveFrom"),
                "url": raw.get("url"),
                "content_length": len(str(raw.get("content_text") or "")),
                "section_count": len(sections),
            },
            ensure_ascii=False,
        ),
        "search_text": _compact(
            " ".join(
                [
                    title,
                    _compact(raw.get("slug")),
                    _compact(raw.get("version")),
                    summary,
                    answer,
                    content,
                ]
            ),
            12000,
        ),
        "url": record.url or "",
        "tags": _tags("class101_terms", raw.get("slug"), record.normalized.get("category")),
        **_tracking_payload(record),
        **_merge_tracking_payload(record),
    }


class NocoDBClient:
    def __init__(self, *, base_url: str, token: str | None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._columns_cache: dict[str, set[str] | None] = {}

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def record_payload(self, record: SourceRecord) -> dict[str, Any]:
        if record.target_table == "slack_cs_data":
            return _slack_cs_payload(record)
        if record.target_table == "class101_changelog":
            return _changelog_payload(record)
        if record.target_table == "class101_promotion":
            return _promotion_payload(record)
        if record.target_table == "product_issue":
            return _product_issue_payload(record)
        if record.target_table == "event_promotion":
            return _event_payload(record)
        if record.target_table == "doc_builder":
            return _doc_builder_payload(record)
        if record.target_table == "class101_terms":
            return _terms_payload(record)
        raise KeyError(f"Unsupported target table: {record.target_table}")

    async def find_existing_record(self, target_table: str, ext_id: str) -> dict[str, Any] | None:
        if not self.token:
            return None
        rows = await self._list_records(
            target_table,
            where=f"(ext_id,eq,{ext_id})",
            limit=1,
            raise_for_status=True,
        )
        return rows[0] if rows else None

    async def find_merge_candidates(
        self,
        record: SourceRecord,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not self.token:
            return []

        columns = await self._table_columns(record.target_table)
        candidates: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        async def add_rows(where: str) -> None:
            rows = await self._list_records(record.target_table, where=where, limit=limit)
            for row in rows:
                row_id = str(row.get("Id") or row.get("id") or row.get("ext_id") or "")
                if row.get("ext_id") == record.source_id or row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
                candidates.append(row)

        key = knowledge_unit_key(record)
        if columns is None or "knowledge_unit_key" in columns:
            await add_rows(f"(knowledge_unit_key,eq,{key})")
        if len(candidates) >= limit:
            return candidates[:limit]

        search_fields = [
            field
            for field in ["search_text", "search_body", "summary", "content", "Title"]
            if columns is None or field in columns
        ]
        for term in _candidate_terms(record):
            for field in search_fields:
                await add_rows(f"({field},like,%{term}%)")
                if len(candidates) >= limit:
                    return candidates[:limit]
        return candidates[:limit]

    async def upsert_record(self, record: SourceRecord) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("NOCO_API_TOKEN is not configured")
        payload = await self._payload_for_write(record.target_table, self.record_payload(record))
        headers = {"xc-token": self.token, "accept": "application/json"}
        table_id = NOCO_TABLE_IDS[record.target_table]
        async with httpx.AsyncClient(timeout=60) as client:
            existing = await self.find_existing_record(record.target_table, record.source_id)
            if existing:
                row_id = existing["Id"]
                response = await client.patch(
                    f"{self.base_url}/api/v2/tables/{table_id}/records",
                    headers={**headers, "content-type": "application/json"},
                    json={**payload, "Id": row_id},
                )
                action = "updated"
            else:
                response = await client.post(
                    f"{self.base_url}/api/v2/tables/{table_id}/records",
                    headers={**headers, "content-type": "application/json"},
                    json=payload,
                )
                action = "created"
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if action != "created" or not _is_unique_conflict(exc):
                    raise
                existing_after_conflict = await self.find_existing_record(
                    record.target_table,
                    record.source_id,
                )
                if not existing_after_conflict:
                    raise
                response = await client.patch(
                    f"{self.base_url}/api/v2/tables/{table_id}/records",
                    headers={**headers, "content-type": "application/json"},
                    json={**payload, "Id": existing_after_conflict["Id"]},
                )
                response.raise_for_status()
                action = "updated_after_unique_conflict"
            return {"action": action, "response": response.json()}

    async def merge_record(
        self,
        record: SourceRecord,
        existing: dict[str, Any],
        decision: MergeDecision,
    ) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("NOCO_API_TOKEN is not configured")
        row_id = existing.get("Id") or existing.get("id")
        if not row_id:
            raise RuntimeError("Cannot merge record without existing row Id")

        refs: list[str] = []
        for ref in [
            str(existing.get("ext_id") or ""),
            *parse_source_refs(existing.get("source_refs")),
            record.source_id,
        ]:
            if ref and ref not in refs:
                refs.append(ref)

        payload = self.record_payload(record)
        payload.pop("ext_id", None)
        payload.update(
            {
                "merge_status": "merged",
                "source_refs": json.dumps(refs, ensure_ascii=False),
                "merged_source_count": len(refs),
                "merge_reason": decision.reason,
                "last_seen_at": record.last_collected_at,
                "canonical_hash": decision.canonical_hash
                or canonical_hash_for(record, source_refs=refs),
            }
        )
        payload = await self._payload_for_write(record.target_table, payload)

        headers = {"xc-token": self.token, "accept": "application/json"}
        table_id = NOCO_TABLE_IDS[record.target_table]
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.patch(
                f"{self.base_url}/api/v2/tables/{table_id}/records",
                headers={**headers, "content-type": "application/json"},
                json={**payload, "Id": row_id},
            )
            response.raise_for_status()
            return {"action": "merged", "response": response.json()}

    async def _list_records(
        self,
        target_table: str,
        *,
        where: str | None = None,
        limit: int = 5,
        raise_for_status: bool = False,
    ) -> list[dict[str, Any]]:
        table_id = NOCO_TABLE_IDS[target_table]
        headers = {"xc-token": self.token or "", "accept": "application/json"}
        params: dict[str, Any] = {"limit": limit}
        if where:
            params["where"] = where
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.base_url}/api/v2/tables/{table_id}/records",
                headers=headers,
                params=params,
            )
        if raise_for_status:
            response.raise_for_status()
        if response.status_code >= 400:
            return []
        return response.json().get("list", [])

    async def _table_columns(self, target_table: str) -> set[str] | None:
        if target_table in self._columns_cache:
            return self._columns_cache[target_table]
        if not self.token:
            self._columns_cache[target_table] = None
            return None
        table_id = NOCO_TABLE_IDS[target_table]
        headers = {"xc-token": self.token, "accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{self.base_url}/api/v2/meta/tables/{table_id}",
                    headers=headers,
                )
        except Exception:  # noqa: BLE001
            self._columns_cache[target_table] = None
            return None
        if response.status_code >= 400:
            self._columns_cache[target_table] = None
            return None
        columns: set[str] = set()
        for column in response.json().get("columns", []):
            for key in ["title", "column_name"]:
                value = column.get(key)
                if value:
                    columns.add(str(value))
        self._columns_cache[target_table] = columns or None
        return self._columns_cache[target_table]

    async def _payload_for_write(
        self,
        target_table: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        columns = await self._table_columns(target_table)
        if columns is None:
            return payload
        return {key: value for key, value in payload.items() if key in columns}


def _is_unique_conflict(exc: httpx.HTTPStatusError) -> bool:
    if exc.response.status_code not in {400, 409, 422}:
        return False
    text = exc.response.text.lower()
    return "unique" in text or "duplicate" in text


def _candidate_terms(record: SourceRecord) -> list[str]:
    text = " ".join(
        str(part or "")
        for part in [
            record.normalized.get("canonical_title"),
            record.title,
            record.normalized.get("summary"),
            record.normalized.get("category"),
            record.normalized.get("intent"),
        ]
    )
    terms: list[str] = []
    for term in re.findall(r"[0-9A-Za-z가-힣]{2,}", text):
        if term not in terms:
            terms.append(term)
    return terms[:5]
