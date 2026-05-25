from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

import httpx


class OCRClient:
    def __init__(self, *, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/health")
            response.raise_for_status()
            return response.json()

    async def extract_from_url(self, image_url: str) -> str:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            image = await client.get(image_url)
            image.raise_for_status()
            suffix = PurePosixPath(image_url.split("?", 1)[0]).suffix or ".png"
            content_type = image.headers.get("content-type", "image/png").split(";", 1)[0]
            response = await client.post(
                f"{self.base_url}/api/ocr/upload",
                files={
                    "file": (
                        f"doc-builder{suffix}",
                        image.content,
                        content_type,
                    )
                },
                data={
                    "lang": "kor+eng",
                    "psm": "6",
                    "preview_lines": "20",
                },
            )
            response.raise_for_status()
            payload = response.json()
            return str(payload.get("text") or payload.get("ocr_text") or "")
