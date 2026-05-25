import pytest

from kb_pipeline.settings import get_settings


@pytest.fixture(autouse=True)
def isolate_env_from_local_dotenv(monkeypatch):
    for key in [
        "SLACK_BOT_TOKEN",
        "NOCO_API_TOKEN",
        "OPENAI_API_KEY",
        "CLASS101_ADMIN_GRAPHQL_URL",
        "CLASS101_ADMIN_AUTHORIZATION",
        "CLASS101_REFRESH_TOKEN",
        "PIPELINE_WEBHOOK_TOKEN",
    ]:
        monkeypatch.setenv(key, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
