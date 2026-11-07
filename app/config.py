from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://firstlisten_app:local-app-password@localhost:5432/firstlisten"
    read_database_url: str = "postgresql+psycopg://firstlisten_reader:local-reader-password@localhost:5432/firstlisten"
    token_ttl_seconds: int = Field(default=2_592_000, ge=60, le=31_536_000)
    chat_requests_per_minute: int = Field(default=20, ge=1, le=1000)
    auth_requests_per_minute: int = Field(default=10, ge=1, le=1000)
    query_timeout_ms: int = Field(default=2000, ge=100, le=30_000)
    display_timezone: str = "Asia/Seoul"
    # Empty key = regex classifier only (tests, offline development).
    pickle_api_key: str = ""
    chat_model: str = "pickle-general"
    llm_base_url: str = "https://llm.pcl.kr/v1"

    @model_validator(mode="after")
    def valid_timezone(self):
        ZoneInfo(self.display_timezone)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

