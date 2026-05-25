from __future__ import annotations

from datetime import datetime

from kb_pipeline.config import CHANNELS

SAMPLE_PARENT_TS = "1775000000.000000"


def sample_slack_thread(channel_id: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    channel = CHANNELS[channel_id]
    parent_text_by_table = {
        "class101_changelog": (
            "[공지] 환불 플로우 내 캐시백 제안 정책이 4월부터 적용됩니다.\n"
            "구독 시작 8일차부터 93일차 사이 유저가 환불 화면에 진입하면 "
            "환불 예정 금액 50% 캐시백을 제안합니다."
        ),
        "class101_promotion": (
            "[프로모션] 4월 죄송 할인 구독 이벤트 대상자 혜택 안내\n"
            "스타터팩은 구독 30일 유지 시 발송, 커피 쿠폰은 5월 29일 일괄 발송됩니다."
        ),
        "product_issue": (
            "[장애] 결제 완료 후 수강권 반영 지연 이슈\n"
            "일부 유저에게 결제 성공 후 멤버십 권한 반영이 지연되고 있습니다."
        ),
        "slack_cs_data": (
            "[상담 얼라인] B2G 수강생 환불 문의 응대 기준 공유\n"
            "계약 기관 지급 건은 일반 개인 결제 환불 정책과 분리해 확인합니다."
        ),
    }
    parent = {
        "type": "message",
        "ts": SAMPLE_PARENT_TS,
        "user": "U_SAMPLE",
        "text": parent_text_by_table[channel.target_table],
    }
    replies = [
        {
            "type": "message",
            "ts": "1775000100.000000",
            "user": "U_NOISE",
            "text": "확인",
        },
        {
            "type": "message",
            "ts": "1775000200.000000",
            "user": "U_BIZ",
            "text": (
                "상담 답변에는 대상 기간, 지급 조건, 예외 조건을 구분해서 안내해주세요. "
                f"채널 기준은 {channel.name}입니다."
            ),
        },
    ]
    return parent, replies


def sample_event_content() -> dict[str, object]:
    return {
        "id": "evc_sample_202604",
        "title": "2026 4월 신규 구독 감사 프로모션",
        "status": "ACTIVE",
        "startedAt": "2026-04-02T00:00:00.000Z",
        "endedAt": "2026-04-30T14:59:59.000Z",
        "updatedAt": "2026-04-02T01:00:00.000Z",
        "promotionId": "promo_sample_202604",
        "quickMenus": [{"link": "https://class101.net/ko/pages/sample-202604"}],
    }


def sample_doc_builder_document() -> tuple[dict[str, object], str]:
    doc = {
        "id": "doc_sample_202604",
        "documentId": "doc_sample_202604",
        "title": "2026 4월 신규 구독 안내 페이지",
        "slug": "sample-docbuilder-202604",
        "version": 7,
        "latestVersion": 7,
        "isPublished": True,
        "createdAt": "2026-04-05T03:00:00.000Z",
        "publishedAt": "2026-04-05T04:00:00.000Z",
        "updatedAt": "2026-04-05T04:00:00.000Z",
        "hrefs": ["https://class101.net/ko/payment/select-subscription-plan"],
        "imageUrls": ["https://cdn.class101.net/images/sample"],
        "url": "https://class101.net/ko/pages/sample-docbuilder-202604",
    }
    ocr_text = (
        "신규 구독 감사 혜택. 4월 5일부터 4월 30일까지 연간 구독 시작 시 "
        "스타터팩과 커피 쿠폰을 제공합니다. 구독 유지 조건을 충족해야 합니다."
    )
    return doc, ocr_text


def collected_at_sample() -> datetime:
    return datetime.fromisoformat("2026-05-11T12:00:00+09:00")
