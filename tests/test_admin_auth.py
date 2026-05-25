import pytest

from kb_pipeline.pipelines.runner import PipelineRunner
from kb_pipeline.settings import get_settings


@pytest.mark.asyncio
async def test_admin_authorization_prefers_explicit_bearer(monkeypatch):
    monkeypatch.setenv("CLASS101_ADMIN_AUTHORIZATION", "Bearer explicit")
    monkeypatch.setenv("CLASS101_REFRESH_TOKEN", "refresh-token")
    get_settings.cache_clear()

    runner = PipelineRunner()

    assert await runner._admin_authorization() == "Bearer explicit"


@pytest.mark.asyncio
async def test_admin_authorization_is_none_without_refresh_or_explicit(monkeypatch):
    monkeypatch.setenv("CLASS101_ADMIN_AUTHORIZATION", "")
    monkeypatch.setenv("CLASS101_REFRESH_TOKEN", "")
    get_settings.cache_clear()

    runner = PipelineRunner()

    assert await runner._admin_authorization() is None
