from __future__ import annotations

import json
import re
from typing import Any

from openai import AsyncOpenAI


class LLMClient:
    def __init__(self, *, api_key: str | None, model: str) -> None:
        self.api_key = api_key
        self.model = model

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def normalize(self, *, source: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            return self._fallback_normalize(source=source, payload=payload)

        client = AsyncOpenAI(api_key=self.api_key)
        response = await client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "당신은 CLASS101 지식베이스 수집 데이터를 정제하는 한국어 에디터입니다. "
                        "반드시 유효한 JSON 객체 하나만 반환하세요. "
                        "마크다운, 코드펜스, 설명문은 금지입니다. "
                        "키는 summary, category, intent, changes, customer_answer, "
                        "internal_note, noise_removed, confidence, knowledge_unit_key, "
                        "canonical_title, core_facts 만 사용하세요. "
                        "summary/customer_answer/changes는 사람이 바로 이해할 수 있는 "
                        "한국어로 작성하세요. "
                        "customer_answer는 요청자/고객에게 안내 가능한 최종 답변문으로 쓰고, "
                        "고객의 요청 내용을 반복하지 마세요. "
                        "knowledge_unit_key는 같은 정책/프로모션/이슈/CS 지식 단위를 "
                        "식별할 수 있는 짧은 snake_case 값으로 작성하세요. "
                        "canonical_title은 병합 후 대표 제목으로 사용될 수 있게 작성하세요. "
                        "core_facts는 병합 판단에 필요한 핵심 사실 배열입니다. "
                        "원문에 없는 연도, 날짜, 금액, 정책 조건은 추정하지 마세요."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"source": source, "payload": payload},
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        try:
            parsed = self._parse_json_object(response.output_text)
            parsed["llm_status"] = "openai"
            parsed["model"] = self.model
            return parsed
        except json.JSONDecodeError:
            fallback = self._fallback_normalize(source=source, payload=payload)
            fallback["llm_status"] = "parse_failed_fallback"
            fallback["raw_llm_output"] = response.output_text[:2000]
            return fallback

    def _parse_json_object(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL)
        if fenced:
            cleaned = fenced.group(1).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                raise
            parsed = json.loads(cleaned[start : end + 1])
        if not isinstance(parsed, dict):
            raise json.JSONDecodeError("Expected JSON object", cleaned, 0)
        return parsed

    def _fallback_normalize(self, *, source: str, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title") or payload.get("text") or payload.get("parent") or source)
        body = str(payload.get("body") or payload.get("ocr_text") or payload.get("text") or "")
        replies = payload.get("replies") or []
        if isinstance(replies, list):
            reply_text = " ".join(str(item) for item in replies)
        else:
            reply_text = str(replies)
        summary = " ".join(part for part in [title, body, reply_text] if part).strip()
        category = self._category_for_source(source)
        intent = "knowledge_base_ingestion"
        knowledge_unit_key = self._fallback_knowledge_unit_key(
            source=source,
            title=title,
            category=category,
            intent=intent,
        )
        return {
            "summary": summary[:500],
            "category": category,
            "intent": intent,
            "changes": [
                {
                    "type": "source_summary",
                    "text": summary[:700],
                }
            ],
            "customer_answer": summary[:700],
            "noise_removed": int(payload.get("noise_removed") or 0),
            "confidence": "fallback",
            "knowledge_unit_key": knowledge_unit_key,
            "canonical_title": title.strip().splitlines()[0][:180] or source,
            "core_facts": [summary[:300]] if summary else [],
            "llm_status": "fallback_no_api_key",
            "source": source,
        }

    def _category_for_source(self, source: str) -> str:
        if source == "event_promotion":
            return "event/promotion"
        if source == "doc_builder":
            return "doc_builder"
        if source == "product_issue":
            return "product_issue"
        if source in {"class101_changelog", "changelog"}:
            return "class101_changelog"
        if source in {"class101_promotion", "promotion"}:
            return "class101_promotion"
        if source == "class101_terms":
            return "class101_terms"
        return "cs_data"

    def _fallback_knowledge_unit_key(
        self,
        *,
        source: str,
        title: str,
        category: str,
        intent: str,
    ) -> str:
        text = " ".join([source, category, intent, title])
        tokens = re.findall(r"[0-9A-Za-z가-힣]{2,}", text.lower())
        if not tokens:
            return source
        return "_".join(tokens[:8])
