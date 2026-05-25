from __future__ import annotations

import re
from typing import Any

import httpx

from kb_pipeline.config import NOCO_TABLE_IDS


class DocBuilderClient:
    def __init__(
        self,
        *,
        graphql_url: str | None,
        authorization: str | None,
        noco_base_url: str | None = None,
        noco_token: str | None = None,
    ) -> None:
        self.graphql_url = graphql_url
        self.authorization = authorization
        self.noco_base_url = noco_base_url.rstrip("/") if noco_base_url else None
        self.noco_token = noco_token
        self._last_seed_total = 0

    @property
    def configured(self) -> bool:
        return bool(
            self.graphql_url
            and self.authorization
            and self.noco_base_url
            and self.noco_token
        )

    @property
    def graphql_configured(self) -> bool:
        return bool(self.graphql_url and self.authorization)

    async def fetch_document_table(
        self,
        *,
        first: int = 20,
        after: str | None = None,
    ) -> dict[str, Any]:
        if not self.graphql_configured:
            raise RuntimeError("DocBuilder GraphQL config is not configured")
        variables: dict[str, Any] = {"first": first, "filter": {}}
        if after:
            variables["after"] = after
        payload = await self._graphql(
            operation_name="DocumentsOnDocumentTable",
            query="""
            query DocumentsOnDocumentTable($first: Int, $after: ID, $filter: DocumentsFilter) {
              documents(first: $first, after: $after, filter: $filter) {
                edges {
                  node {
                    id
                    slug
                    author { id displayName __typename }
                    title
                    version
                    latestVersion
                    isPublished
                    isDeleted
                    createdAt
                    publishedAt
                    __typename
                  }
                  cursor
                  __typename
                }
                pageInfo { hasNextPage endCursor __typename }
                __typename
              }
            }
            """,
            variables=variables,
        )
        return payload["data"]["documents"]

    async def fetch_documents(self, *, first: int = 50, skip: int = 0) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("DocBuilder GraphQL/NocoDB config is not configured")

        seeds = await self._fetch_nocodb_seeds(first=first, skip=skip)
        edges: list[dict[str, Any]] = []
        for seed in seeds:
            id_or_slug = self._id_or_slug_from_seed(seed)
            if not id_or_slug:
                continue
            try:
                doc = await self.fetch_document_by_id_or_slug(id_or_slug)
            except Exception as exc:  # noqa: BLE001
                doc = {
                    "documentId": str(seed.get("ext_id") or id_or_slug),
                    "slug": self._slug_from_url(str(seed.get("url") or "")) or id_or_slug,
                    "title": str(seed.get("Title") or id_or_slug),
                    "isPublished": bool(seed.get("status")),
                    "load_error": f"{type(exc).__name__}: {exc}",
                }
            doc["seedId"] = seed.get("Id")
            doc["seedTitle"] = seed.get("Title") or ""
            doc["seedExtId"] = seed.get("ext_id") or ""
            doc["url"] = seed.get("url") or self._url_from_slug(doc.get("slug"))
            doc["createdAt"] = seed.get("created_at") or seed.get("CreatedAt")
            doc["updatedAt"] = seed.get("updated_at") or seed.get("UpdatedAt")
            doc["publishedAt"] = doc.get("updatedAt") or doc.get("createdAt")
            edges.append({"node": doc})
        return {
            "totalCount": self._last_seed_total,
            "edges": edges,
        }

    async def fetch_document_by_id_or_slug(self, id_or_slug: str) -> dict[str, Any]:
        norm = await self.resolve_document_identity(id_or_slug)
        slug = norm.get("slug") or id_or_slug
        loaded = await self._graphql(
            operation_name="DocumentBySlugOnDocumentLoader",
            query="""
            query DocumentBySlugOnDocumentLoader($slug: String!, $version: Int) {
              documentBySlug(slug: $slug, version: $version) {
                title
                version
                isPublished
                slug
                documentId
                content
                isMobileView
                latestVersion
                documentTheme {
                  breakpoints
                  viewportWidths
                  mode
                  __typename
                }
                __typename
              }
            }
            """,
            variables={"slug": slug},
        )
        doc = loaded.get("data", {}).get("documentBySlug") or {}
        if norm.get("documentId") and not doc.get("documentId"):
            doc["documentId"] = norm["documentId"]
        if slug and not doc.get("slug"):
            doc["slug"] = slug
        self._enrich_content_metadata(doc)
        return doc

    async def resolve_document_identity(self, id_or_slug: str) -> dict[str, Any]:
        route = await self._graphql(
            operation_name="DocumentByIdOrSlugOnDocumentRouteGuard",
            query="""
            query DocumentByIdOrSlugOnDocumentRouteGuard($idOrSlug: String!) {
              documentByIdOrSlug(idOrSlug: $idOrSlug) {
                documentId
                slug
                __typename
              }
            }
            """,
            variables={"idOrSlug": id_or_slug},
        )
        return route.get("data", {}).get("documentByIdOrSlug") or {}

    async def fetch_document_by_slug(self, slug: str) -> dict[str, Any]:
        loaded = await self._graphql(
            operation_name="DocumentBySlugOnDocumentLoader",
            query="""
            query DocumentBySlugOnDocumentLoader($slug: String!, $version: Int) {
              documentBySlug(slug: $slug, version: $version) {
                title
                version
                isPublished
                slug
                documentId
                content
                isMobileView
                latestVersion
                documentTheme {
                  breakpoints
                  viewportWidths
                  mode
                  __typename
                }
                __typename
              }
            }
            """,
            variables={"slug": slug},
        )
        doc = loaded.get("data", {}).get("documentBySlug") or {}
        self._enrich_content_metadata(doc)
        return doc

    async def _graphql(
        self,
        *,
        operation_name: str,
        query: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self.graphql_url,
                json={
                    "operationName": operation_name,
                    "query": query,
                    "variables": variables,
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
                    f"DocBuilder GraphQL HTTP {response.status_code}: {response.text[:1200]}"
                )
            payload = response.json()
            if payload.get("errors"):
                raise RuntimeError(f"DocBuilder GraphQL failed: {payload['errors']}")
            return payload

    async def _fetch_nocodb_seeds(self, *, first: int, skip: int) -> list[dict[str, Any]]:
        table_id = NOCO_TABLE_IDS["doc_builder"]
        page = (skip // first) + 1
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.noco_base_url}/api/v2/tables/{table_id}/records",
                headers={"xc-token": self.noco_token or "", "accept": "application/json"},
                params={"limit": first, "page": page},
            )
            if response.is_error:
                raise RuntimeError(
                    f"NocoDB doc_builder seed HTTP {response.status_code}: {response.text[:1200]}"
                )
            payload = response.json()
        self._last_seed_total = int(payload.get("pageInfo", {}).get("totalRows") or 0)
        return list(payload.get("list") or [])

    def _id_or_slug_from_seed(self, seed: dict[str, Any]) -> str:
        return str(
            seed.get("ext_id")
            or self._slug_from_url(str(seed.get("url") or ""))
            or seed.get("Title")
            or ""
        ).strip()

    def _slug_from_url(self, url: str) -> str:
        marker = "/pages/"
        if marker not in url:
            return ""
        slug = url.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0]
        return slug.strip("/")

    def _url_from_slug(self, slug: object) -> str:
        value = str(slug or "").strip()
        return f"https://class101.net/ko/pages/{value}" if value else ""

    def _enrich_content_metadata(self, doc: dict[str, Any]) -> None:
        content = str(doc.get("content") or "")
        hrefs = self._dedupe(re.findall(r'href="([^"]+)"', content))[:30]
        image_urls = self._dedupe(
            match.rstrip(")\"',;")
            for match in re.findall(
                r"https://cdn\.class101\.net/(?:images|attachment)/[A-Za-z0-9._~:/?#[\]@!$&'()*+,;=%-]+",
                content,
            )
        )[:50]
        components = self._dedupe(re.findall(r"<(\w+Block)\b", content))[:30]
        text_snippets = [
            snippet.strip()
            for snippet in re.findall(r">([^<>{}][^<>]{2,100})<", content)
            if snippet.strip()
        ][:20]
        doc["hrefs"] = hrefs
        doc["imageUrls"] = image_urls
        doc["components"] = components
        doc["textSnippets"] = text_snippets
        doc["contentOriginalLength"] = len(content)

    def _dedupe(self, values) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for value in values:
            item = str(value or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out
