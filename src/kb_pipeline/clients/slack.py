from __future__ import annotations

from typing import Any

import httpx


class SlackClient:
    def __init__(self, token: str | None) -> None:
        self.token = token

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def conversations_history(
        self,
        *,
        channel_id: str,
        oldest: str,
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("SLACK_BOT_TOKEN is not configured")
        params = {"channel": channel_id, "oldest": oldest, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                "https://slack.com/api/conversations.history",
                params=params,
                headers={"Authorization": f"Bearer {self.token}"},
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise RuntimeError(f"Slack history failed: {payload.get('error')}")
            return payload

    async def conversations_replies(
        self,
        *,
        channel_id: str,
        thread_ts: str,
        limit: int = 200,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("SLACK_BOT_TOKEN is not configured")
        params = {"channel": channel_id, "ts": thread_ts, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                "https://slack.com/api/conversations.replies",
                params=params,
                headers={"Authorization": f"Bearer {self.token}"},
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise RuntimeError(f"Slack replies failed: {payload.get('error')}")
            return payload

