from __future__ import annotations

from typing import Any

import httpx


class EventClient:
    def __init__(self, *, graphql_url: str | None, authorization: str | None) -> None:
        self.graphql_url = graphql_url
        self.authorization = authorization

    @property
    def configured(self) -> bool:
        return bool(self.graphql_url and self.authorization)

    async def fetch_event_contents(self, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("CLASS101 admin GraphQL config is not configured")
        query = """
        query EventContentsOnAdminEventList($offset: Int = 0, $limit: Int = 20) {
          eventContents(offset: $offset, limit: $limit) {
            totalCount
            edges {
              cursor
              node {
                id
                title
                startedAt
                endedAt
                promotionId
                enableQuickMenu
                quickMenus { link __typename }
                discountBadge { image { url filename size type __typename } __typename }
                categoryBanner { buttonName __typename }
                status
                __typename
              }
              __typename
            }
            pageInfo { hasNextPage endCursor __typename }
            __typename
          }
        }
        """
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self.graphql_url,
                json={
                    "operationName": "EventContentsOnAdminEventList",
                    "query": query,
                    "variables": {"offset": offset, "limit": limit},
                },
                headers={
                    "Authorization": self.authorization or "",
                    "apollographql-client-name": "admin-csr",
                    "Accept-Language": "ko",
                    "Content-Type": "application/json",
                },
            )
            if response.is_error:
                raise RuntimeError(
                    f"Event GraphQL HTTP {response.status_code}: {response.text[:1200]}"
                )
            payload = response.json()
            if payload.get("errors"):
                raise RuntimeError(f"Event GraphQL failed: {payload['errors']}")
            return payload["data"]["eventContents"]
