from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal

from kb_pipeline.models import SourceRecord
from kb_pipeline.normalizers.common import build_source_hash

MergeAction = Literal["merge", "new", "needs_review"]


@dataclass(frozen=True)
class MergeDecision:
    decision: MergeAction
    target_ext_id: str | None = None
    confidence: float = 0.0
    reason: str = ""
    merge_type: str = "none"
    canonical_hash: str | None = None


def merge_metadata(record: SourceRecord, *, status: str = "standalone") -> dict[str, Any]:
    key = knowledge_unit_key(record)
    canonical_title = canonical_title_for(record)
    return {
        "knowledge_unit_key": key,
        "canonical_title": canonical_title,
        "merge_status": status,
        "source_refs": json.dumps([record.source_id], ensure_ascii=False),
        "merged_source_count": 1,
        "merge_reason": "",
        "last_seen_at": record.last_collected_at,
        "canonical_hash": record.source_hash,
    }


def knowledge_unit_key(record: SourceRecord) -> str:
    normalized = record.normalized or {}
    explicit = _clean_key(normalized.get("knowledge_unit_key"))
    if explicit:
        return explicit
    parts = [
        normalized.get("category"),
        normalized.get("intent"),
        normalized.get("canonical_title"),
        record.title,
    ]
    text = " ".join(str(part or "") for part in parts)
    tokens = _tokens(text)[:8]
    if tokens:
        return "_".join(tokens)
    return "ku_" + build_source_hash(
        {
            "target_table": record.target_table,
            "title": record.title,
            "summary": normalized.get("summary"),
        }
    )[:16]


def canonical_title_for(record: SourceRecord) -> str:
    normalized = record.normalized or {}
    for value in [normalized.get("canonical_title"), record.title, normalized.get("summary")]:
        text = str(value or "").strip()
        if text:
            return text[:180]
    return record.source_id


def decide_merge(record: SourceRecord, candidates: list[dict[str, Any]]) -> MergeDecision:
    if not candidates:
        return MergeDecision(decision="new", reason="no merge candidates")

    new_key = knowledge_unit_key(record)
    best: tuple[float, dict[str, Any], str] | None = None
    for candidate in candidates:
        candidate_ext_id = str(candidate.get("ext_id") or "")
        if candidate_ext_id == record.source_id:
            continue

        candidate_key = _candidate_key(candidate)
        if new_key and candidate_key and new_key == candidate_key:
            return MergeDecision(
                decision="merge",
                target_ext_id=candidate_ext_id or None,
                confidence=0.96,
                reason=f"knowledge_unit_key matched: {new_key}",
                merge_type="same_knowledge_unit",
                canonical_hash=canonical_hash_for(
                    record,
                    source_refs=[candidate_ext_id, record.source_id],
                ),
            )

        similarity = _similarity(_record_compare_text(record), _candidate_compare_text(candidate))
        if best is None or similarity > best[0]:
            best = (similarity, candidate, "semantic text similarity")

    if not best:
        return MergeDecision(decision="new", reason="no comparable candidates")

    score, candidate, reason = best
    target_ext_id = str(candidate.get("ext_id") or "") or None
    if score >= 0.84:
        return MergeDecision(
            decision="merge",
            target_ext_id=target_ext_id,
            confidence=round(score, 4),
            reason=reason,
            merge_type="similar_text",
            canonical_hash=canonical_hash_for(
                record,
                source_refs=[target_ext_id or "", record.source_id],
            ),
        )
    if score >= 0.68:
        return MergeDecision(
            decision="needs_review",
            target_ext_id=target_ext_id,
            confidence=round(score, 4),
            reason=reason,
            merge_type="candidate_only",
        )
    return MergeDecision(
        decision="new",
        confidence=round(score, 4),
        reason="best candidate is below merge threshold",
    )


def canonical_hash_for(record: SourceRecord, *, source_refs: list[str]) -> str:
    return build_source_hash(
        {
            "knowledge_unit_key": knowledge_unit_key(record),
            "canonical_title": canonical_title_for(record),
            "source_refs": sorted(ref for ref in source_refs if ref),
            "source_hash": record.source_hash,
        }
    )


def parse_source_refs(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item or "").strip()]
    except json.JSONDecodeError:
        pass
    return [item.strip() for item in text.split(",") if item.strip()]


def _candidate_key(candidate: dict[str, Any]) -> str:
    for key in ["knowledge_unit_key", "Knowledge Unit Key"]:
        cleaned = _clean_key(candidate.get(key))
        if cleaned:
            return cleaned
    for container_key in ["refined_data", "workflow_response", "normalized"]:
        value = candidate.get(container_key)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = None
        if isinstance(value, dict):
            cleaned = _clean_key(value.get("knowledge_unit_key"))
            if cleaned:
                return cleaned
    return ""


def _record_compare_text(record: SourceRecord) -> str:
    normalized = record.normalized or {}
    return " ".join(
        str(part or "")
        for part in [
            knowledge_unit_key(record),
            canonical_title_for(record),
            normalized.get("summary"),
            normalized.get("category"),
            normalized.get("intent"),
            normalized.get("customer_answer"),
        ]
    )


def _candidate_compare_text(candidate: dict[str, Any]) -> str:
    values: list[str] = []
    for key in [
        "knowledge_unit_key",
        "canonical_title",
        "Title",
        "summary",
        "benefit_summary",
        "condition_summary",
        "impact_summary",
        "inquiry",
        "resolution",
        "search_text",
        "search_body",
        "content",
    ]:
        values.append(str(candidate.get(key) or ""))
    return " ".join(values)


def _similarity(left: str, right: str) -> float:
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens or not right_tokens:
        return SequenceMatcher(None, left, right).ratio()
    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = SequenceMatcher(None, left, right).ratio()
    return max(overlap, sequence)


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", str(text or ""))
        if token.strip()
    ]


def _clean_key(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^0-9a-z가-힣]+", "_", text)
    return text.strip("_")
