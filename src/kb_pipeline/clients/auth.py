from __future__ import annotations

from typing import Any

import httpx


class Class101AuthClient:
    def __init__(self, *, firebase_token_url: str, refresh_token: str | None) -> None:
        self.firebase_token_url = firebase_token_url
        self.refresh_token = refresh_token

    @property
    def configured(self) -> bool:
        return bool(self.refresh_token)

    async def admin_authorization(self) -> str | None:
        if not self.refresh_token:
            return None
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.firebase_token_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                },
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        id_token = payload.get("id_token")
        if not id_token:
            raise RuntimeError("Firebase token response missing id_token")
        return f"Bearer {id_token}"
