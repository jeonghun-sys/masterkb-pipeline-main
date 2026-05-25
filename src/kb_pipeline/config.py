from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
COLLECTION_CUTOFF = datetime(2026, 4, 1, 0, 0, tzinfo=KST)


@dataclass(frozen=True)
class SlackChannelConfig:
    channel_id: str
    name: str
    target_table: str
    source_type: str
    enabled: bool = True


@dataclass(frozen=True)
class TermsConfig:
    slug: str
    title: str
    url: str


CHANNELS: dict[str, SlackChannelConfig] = {
    "C01F3FELHL5": SlackChannelConfig(
        channel_id="C01F3FELHL5",
        name="all-breaking-changes",
        target_table="class101_changelog",
        source_type="changelog",
    ),
    "C05U3LUPR6V": SlackChannelConfig(
        channel_id="C05U3LUPR6V",
        name="all-promotion-sharing",
        target_table="class101_promotion",
        source_type="promotion",
    ),
    "C01FCNMKKTN": SlackChannelConfig(
        channel_id="C01FCNMKKTN",
        name="bizops-cx-tck-align",
        target_table="slack_cs_data",
        source_type="cs",
    ),
    "C01J93WPXN3": SlackChannelConfig(
        channel_id="C01J93WPXN3",
        name="cx-tck-complaints",
        target_table="slack_cs_data",
        source_type="cs",
    ),
    "C01FWDB5V88": SlackChannelConfig(
        channel_id="C01FWDB5V88",
        name="cx-tck-clients",
        target_table="slack_cs_data",
        source_type="cs",
    ),
    "C01FE91AUNP": SlackChannelConfig(
        channel_id="C01FE91AUNP",
        name="cx-tck-inside",
        target_table="slack_cs_data",
        source_type="cs",
    ),
    "C01FCNLHMT6": SlackChannelConfig(
        channel_id="C01FCNLHMT6",
        name="cx-tck-mates",
        target_table="slack_cs_data",
        source_type="cs",
    ),
    "C08BGKAQM33": SlackChannelConfig(
        channel_id="C08BGKAQM33",
        name="product-issues",
        target_table="product_issue",
        source_type="product_issue",
    ),
}


TERMS: list[TermsConfig] = [
    TermsConfig(
        slug="use",
        title="이용약관",
        url="https://class101.net/ko/docs/terms/use?viewMode=svod",
    ),
    TermsConfig(
        slug="privacy",
        title="개인정보 처리방침",
        url="https://class101.net/ko/docs/terms/privacy?viewMode=svod",
    ),
    TermsConfig(
        slug="giftcard",
        title="기프트카드 및 캐시",
        url="https://class101.net/ko/docs/terms/giftcard?viewMode=svod",
    ),
    TermsConfig(
        slug="refund",
        title="환불정책",
        url="https://class101.net/ko/docs/terms/refund?viewMode=svod",
    ),
    TermsConfig(
        slug="youthProtectionPolicy",
        title="청소년 보호 정책",
        url="https://class101.net/ko/docs/terms/youthProtectionPolicy?viewMode=svod",
    ),
]


NOCO_TABLE_IDS: dict[str, str] = {
    "event_promotion": "m2tyngqo6k5lc0o",
    "doc_builder": "mbl3xz7zt8oklx3",
    "product_issue": "m4p26uatfpyeatp",
    "slack_cs_data": "m38riwogsirr7cm",
    "class101_changelog": "m6fcosxoep6syxz",
    "class101_promotion": "mb2j1iqf6dd7mu6",
    "class101_terms": "mzvo0243h2eiddh",
}
