from __future__ import annotations

import html
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from kb_pipeline.models import SourceRecord
from kb_pipeline.normalizers.common import build_source_hash


class _TermsTextParser(HTMLParser):
    block_tags = {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "li",
        "ol",
        "ul",
        "table",
        "tr",
        "div",
        "br",
    }

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        text = html.unescape(data).strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        text = " ".join(self.parts)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s*", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


class _TermsBlockParser(HTMLParser):
    block_tags = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th"}

    def __init__(self) -> None:
        super().__init__()
        self.current_tag: str | None = None
        self.current_parts: list[str] = []
        self.blocks: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.block_tags:
            self._flush()
            self.current_tag = tag
            self.current_parts = []
        elif tag == "br" and self.current_tag:
            self.current_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == self.current_tag:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self.current_tag:
            return
        text = html.unescape(data).strip()
        if text:
            self.current_parts.append(text)

    def _flush(self) -> None:
        if not self.current_tag:
            return
        text = re.sub(r"\s+", " ", " ".join(self.current_parts)).strip()
        if text:
            self.blocks.append({"tag": self.current_tag, "text": text})
        self.current_tag = None
        self.current_parts = []

    def close(self) -> None:
        self._flush()
        super().close()


def extract_current_terms_document(
    *,
    html_text: str,
    slug: str,
    title: str,
    url: str,
) -> dict[str, Any]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html_text,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError("CLASS101 terms page does not include __NEXT_DATA__")
    payload = json.loads(html.unescape(match.group(1)))
    data = payload.get("props", {}).get("apolloState", {}).get("data", {})
    term = _find_terms_v2(data=data, slug=slug)
    current_ref = (term.get("currentVersion") or {}).get("__ref")
    if not current_ref:
        raise ValueError(f"CLASS101 terms page has no currentVersion for {slug}")
    version = data.get(current_ref) or {}
    content_html = str(version.get("content") or "")
    content_text = terms_html_to_text(content_html)
    sections = terms_html_to_sections(content_html)
    return {
        "slug": slug,
        "title": title,
        "url": url,
        "version_id": str(version.get("id") or current_ref.split(":", 1)[-1]),
        "version": str(version.get("version") or ""),
        "effectiveFrom": str(version.get("effectiveFrom") or ""),
        "content_html": content_html,
        "content_text": content_text,
        "sections": sections,
        "section_markdown": terms_sections_to_markdown(sections),
    }


def terms_html_to_text(content_html: str) -> str:
    parser = _TermsTextParser()
    parser.feed(content_html)
    return parser.text()


def terms_html_to_sections(content_html: str) -> list[dict[str, Any]]:
    parser = _TermsBlockParser()
    parser.feed(content_html)
    parser.close()
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for block in parser.blocks:
        tag = block["tag"]
        text = block["text"]
        if tag.startswith("h") and tag[1:].isdigit():
            if current and (current.get("items") or current.get("heading")):
                sections.append(current)
            current = {
                "heading": text,
                "level": int(tag[1:]),
                "items": [],
            }
            continue
        if current is None:
            current = {"heading": "본문", "level": 0, "items": []}
        current["items"].append(text)
    if current and (current.get("items") or current.get("heading")):
        sections.append(current)
    return sections or [
        {
            "heading": "본문",
            "level": 0,
            "items": [terms_html_to_text(content_html)],
        }
    ]


def terms_sections_to_markdown(sections: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for section in sections:
        heading = str(section.get("heading") or "").strip()
        level = int(section.get("level") or 2)
        if heading:
            hashes = "#" * min(max(level, 2), 4)
            chunks.append(f"{hashes} {heading}")
        for item in section.get("items") or []:
            text = str(item or "").strip()
            if text:
                chunks.append(text)
        chunks.append("")
    return "\n".join(chunks).strip()


def terms_to_record(
    *,
    doc: dict[str, Any],
    collected_at: datetime,
    normalized: dict[str, Any] | None = None,
) -> SourceRecord:
    slug = str(doc.get("slug") or "").strip()
    title = str(doc.get("title") or slug or "CLASS101 약관")
    hash_payload = {
        "slug": slug,
        "version_id": doc.get("version_id"),
        "version": doc.get("version"),
        "effectiveFrom": doc.get("effectiveFrom"),
        "content_text": doc.get("content_text"),
    }
    return SourceRecord(
        source="class101_terms",
        source_id=f"terms:{slug}",
        target_table="class101_terms",
        title=title,
        raw=doc,
        normalized=normalized or {"summary": title, "category": "약관"},
        source_updated_ts=str(doc.get("effectiveFrom") or doc.get("version") or ""),
        source_hash=build_source_hash(hash_payload),
        last_collected_at=collected_at.isoformat(),
        url=str(doc.get("url") or ""),
    )


def _find_terms_v2(*, data: dict[str, Any], slug: str) -> dict[str, Any]:
    for value in data.values():
        if isinstance(value, dict) and value.get("__typename") == "TermsV2":
            if value.get("slug") == slug:
                return value
    raise ValueError(f"CLASS101 terms page has no TermsV2 for {slug}")
