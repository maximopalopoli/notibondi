from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str

# Settings are built on first call, not at import time, so importing this
# module never fails. lru_cache makes every later call return the same instance.
@lru_cache
def get_settings() -> Settings:
    return Settings()
