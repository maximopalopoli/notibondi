from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The app connects as notibondi_app (reads, and writes only route_names).
    # Migrations and the data imports connect as the owner, with
    # ADMIN_DATABASE_URL; without it they use DATABASE_URL too
    database_url: str
    admin_database_url: str | None = None
    gcba_client_id: str
    gcba_client_secret: SecretStr
    gcba_base_url: str = "https://apitransporte.buenosaires.gob.ar"
    live_feeds: Literal["gcba", "fixtures", "off"] = "gcba"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    # Nominatim's policy asks for a User-Agent that says who is calling
    nominatim_user_agent: str = (
        "notibondi/0.1 (https://github.com/maximopalopoli/notibondi)"
    )


# Settings are built on first call, not at import time, so importing this
# module never fails. lru_cache makes every later call return the same instance.
@lru_cache
def get_settings() -> Settings:
    return Settings()
