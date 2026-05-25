from kb_pipeline.clients.nocodb import NocoDBClient
from kb_pipeline.models import SourceRecord


def make_slack_record(target_table: str = "slack_cs_data") -> SourceRecord:
    return SourceRecord(
        source="slack",
        source_id="C01J93WPXN3:1778136170.724039",
        target_table=target_table,
        title="<@U123><@U456> cc. <@U789>",
        raw={
            "channel": "cx-tck-complaints",
            "parent": {
                "text": (
                    "<@U123><@U456> cc. <@U789>\n\n"
                    "*[*:rotating_light:*민원공유]*\n"
                    "• *상황 분류 :* 소비자원 신고\n"
                    "• *상품명 :* Class101+ 연간 구독\n"
                )
            },
            "replies": [{"text": "환불 처리 완료되었습니다."}],
        },
        normalized={
            "summary": "Class101+ 연간 구독 갱신 결제에 대한 전액 환불 민원입니다.",
            "category": "민원 처리",
            "intent": "전액 환불 요청",
            "changes": ["환불 처리 완료", "강제 환불 권한 이슈 확인"],
            "customer_answer": "요청하신 연간 구독 결제 건은 전액 환불 처리되었습니다.",
            "internal_note": "권한 정합성 점검 필요",
            "noise_removed": 2,
            "llm_status": "openai",
            "model": "gpt-4.1-mini",
        },
        source_updated_ts="1778136170.724039",
        source_latest_reply_ts="1778141143.846499",
        source_reply_count=44,
        source_hash="hash",
        last_collected_at="2026-05-11T13:33:50+09:00",
        url="https://101inc.slack.com/archives/C01J93WPXN3/p1778136170724039",
        thread_ref="C01J93WPXN3:1778136170.724039",
    )


def test_slack_cs_payload_uses_table_fields_and_clean_title():
    payload = NocoDBClient(base_url="https://noco.example", token=None).record_payload(
        make_slack_record()
    )

    assert payload["Title"] == "민원공유 / 전액 환불 요청"
    assert payload["content_type"] == "slack_cs_data"
    assert payload["source_channel"] == "cx-tck-complaints"
    assert payload["slack_ts"] == "1778136170.724039"
    assert payload["inquiry"] == "Class101+ 연간 구독 갱신 결제에 대한 전액 환불 민원입니다."
    assert payload["resolution"] == "요청하신 연간 구독 결제 건은 전액 환불 처리되었습니다."
    assert "raw_data" not in payload
    assert "workflow_answer" not in payload
    assert "search_body" not in payload


def test_class101_changelog_payload_uses_changelog_fields():
    payload = NocoDBClient(base_url="https://noco.example", token=None).record_payload(
        make_slack_record(target_table="class101_changelog")
    )

    assert payload["summary"] == "Class101+ 연간 구독 갱신 결제에 대한 전액 환불 민원입니다."
    assert payload["impact_summary"] == "환불 처리 완료 / 강제 환불 권한 이슈 확인"
    assert payload["source_channel"] == "cx-tck-complaints"
    assert payload["thread_ref"] == "C01J93WPXN3:1778136170.724039"
    assert "workflow_answer" not in payload
    assert "content_type" not in payload


def test_slack_title_falls_back_to_category_and_intent_for_greeting():
    record = make_slack_record(target_table="class101_promotion")
    record.title = "안녕하세요!"
    record.raw["parent"]["text"] = "안녕하세요!"
    record.normalized["category"] = "프로모션 안내"
    record.normalized["intent"] = "스타터팩·커피 쿠폰 발송 안내"

    payload = NocoDBClient(base_url="https://noco.example", token=None).record_payload(record)

    assert payload["Title"] == "프로모션 안내 / 스타터팩·커피 쿠폰 발송 안내"


def test_event_promotion_payload_accepts_docbuilder_ocr_source():
    record = SourceRecord(
        source="event_promotion",
        source_id="doc-1",
        target_table="event_promotion",
        title="TVOD-2605-01",
        raw={
            "source_kind": "doc_builder_document",
            "slug": "TVOD-2605-01",
            "isPublished": True,
            "isDeleted": False,
            "version": 22,
            "latestVersion": 22,
            "publishedAt": "2026-05-11T02:57:00.000Z",
            "hrefs": ["https://class101.net/ko/payment/select-subscription-plan"],
            "imageUrls": ["https://cdn.class101.net/images/sample"],
            "ocr_text": "5월 상시 선착순 프로모션. 5월 1일부터 5월 12일까지 진행됩니다.",
        },
        normalized={
            "summary": "5월 상시 선착순 프로모션 안내",
            "category": "프로모션",
            "customer_answer": "5월 상시 선착순 혜택은 이벤트 기간 내 구독 시 적용됩니다.",
        },
        source_updated_ts="2026-05-11T02:57:00.000Z",
        source_hash="hash",
        last_collected_at="2026-05-11T12:00:00+09:00",
        url="https://class101.net/ko/pages/TVOD-2605-01",
    )

    payload = NocoDBClient(base_url="https://noco.example", token=None).record_payload(record)

    assert payload["Title"] == "TVOD-2605-01"
    assert payload["status"] is True
    assert payload["workflow_answer"] == "5월 상시 선착순 프로모션 안내"
    assert "doc_builder_document" in payload["tags"]
    assert "published" in payload["tags"]
    assert "5월 상시 선착순 프로모션" in payload["body_md"]
    assert "https://class101.net/ko/pages/TVOD-2605-01" in payload["search_body"]
    assert "event_start_date" not in payload
    assert "event_end_date" not in payload
    assert "origin_created_at" not in payload


def test_payload_includes_merge_metadata_when_normalized_has_knowledge_unit():
    record = make_slack_record(target_table="class101_promotion")
    record.normalized.update(
        {
            "knowledge_unit_key": "subscription_refund_cashback_50pct",
            "canonical_title": "구독 중도 환불 유저 대상 50% 캐시백 제안",
            "merge_status": "standalone",
        }
    )

    payload = NocoDBClient(base_url="https://noco.example", token=None).record_payload(record)

    assert payload["knowledge_unit_key"] == "subscription_refund_cashback_50pct"
    assert payload["canonical_title"] == "구독 중도 환불 유저 대상 50% 캐시백 제안"
    assert payload["merge_status"] == "standalone"
    assert payload["source_refs"] == '["C01J93WPXN3:1778136170.724039"]'
    assert payload["merged_source_count"] == 1
    assert payload["canonical_hash"] == "hash"


def test_class101_terms_payload_uses_terms_table_fields():
    record = SourceRecord(
        source="class101_terms",
        source_id="terms:refund",
        target_table="class101_terms",
        title="환불정책",
        raw={
            "slug": "refund",
            "version_id": "1082",
            "version": "2026-04-19",
            "effectiveFrom": "2026-04-19T15:00:00.000Z",
            "content_text": "환불정책 본문입니다.",
            "sections": [
                {"heading": "환불정책", "level": 1, "items": ["환불정책 본문입니다."]}
            ],
            "section_markdown": "## 환불정책\n환불정책 본문입니다.",
        },
        normalized={
            "summary": "구독 상품 환불 기준",
            "category": "약관",
            "intent": "환불정책",
            "changes": ["구독 상품 조건별 환불 기준 안내"],
            "customer_answer": "환불정책은 구독 상품의 조건별 환불 기준을 안내합니다.",
            "knowledge_unit_key": "class101_terms_refund",
            "canonical_title": "CLASS101 환불정책",
        },
        source_updated_ts="2026-04-19T15:00:00.000Z",
        source_hash="terms-hash",
        last_collected_at="2026-05-14T12:00:00+09:00",
        url="https://class101.net/ko/docs/terms/refund?viewMode=svod",
    )

    payload = NocoDBClient(base_url="https://noco.example", token=None).record_payload(record)

    assert payload["Title"] == "환불정책"
    assert payload["ext_id"] == "terms:refund"
    assert payload["content_type"] == "class101_terms"
    assert payload["terms_key"] == "refund"
    assert payload["version"] == "2026-04-19"
    assert payload["effective_from"] == "2026-04-19T15:00:00.000Z"
    assert payload["content"] == "## 환불정책\n환불정책 본문입니다."
    assert payload["section_count"] == 1
    assert "환불정책 본문입니다." in payload["structured_sections"]
    assert "sections" in payload["workflow_response"]
    assert "구독 상품 환불 기준" in payload["search_text"]
    assert payload["knowledge_unit_key"] == "class101_terms_refund"
