from functools import lru_cache

from sqlalchemy import create_engine, Engine

from notibondi.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url)
