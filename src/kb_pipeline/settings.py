from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
    )

    environment: str = Field(default="local", alias="KB_PIPELINE_ENV")
    state_db: str = Field(default=".data/kb_pipeline.sqlite3", alias="KB_PIPELINE_STATE_DB")
    pipeline_webhook_token: str | None = Field(default=None, alias="PIPELINE_WEBHOOK_TOKEN")
    monitoring_enabled: bool = Field(default=False, alias="MONITORING_ENABLED")
    monitoring_slack_channel_id: str | None = Field(
        default=None,
        alias="MONITORING_SLACK_CHANNEL_ID",
    )

    slack_bot_token: str | None = Field(default=None, alias="SLACK_BOT_TOKEN")
    noco_base_url: str = Field(default="https://mkt-nocodb.class101.net", alias="NOCO_BASE_URL")
    noco_api_token: str | None = Field(default=None, alias="NOCO_API_TOKEN")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")

    class101_admin_graphql_url: str | None = Field(
        default=None,
        alias="CLASS101_ADMIN_GRAPHQL_URL",
    )
    class101_admin_authorization: str | None = Field(
        default=None,
        alias="CLASS101_ADMIN_AUTHORIZATION",
    )
    class101_refresh_token: str | None = Field(default=None, alias="CLASS101_REFRESH_TOKEN")
    class101_firebase_token_url: str = Field(
        default=(
            "https://securetoken.googleapis.com/v1/token?"
            "key=AIzaSyBOybGuB69OpLttriljMZUvEpdFXTqahFY"
        ),
        alias="CLASS101_FIREBASE_TOKEN_URL",
    )

    ocr_base_url: str = Field(
        default="https://101chatbottest-main-production.up.railway.app",
        alias="OCR_BASE_URL",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
