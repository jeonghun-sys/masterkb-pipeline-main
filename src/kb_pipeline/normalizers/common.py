from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from kb_pipeline.config import COLLECTION_CUTOFF, KST


def to_kst(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(KST)


def is_after_cutoff(value: datetime) -> bool:
    return to_kst(value) >= COLLECTION_CUTOFF


def parse_slack_ts(ts: str) -> datetime:
    seconds = float(ts)
    return datetime.fromtimestamp(seconds, tz=ZoneInfo("UTC")).astimezone(KST)


def stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_source_hash(data: Any) -> str:
    return hashlib.sha256(stable_json(data).encode("utf-8")).hexdigest()

