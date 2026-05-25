from __future__ import annotations

import httpx


class TermsClient:
    async def fetch(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
