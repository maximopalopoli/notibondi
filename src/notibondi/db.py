from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine

from notibondi.config import get_settings


def get_conn() -> Iterator[Connection]:
    with get_engine().connect() as conn:
        yield conn


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url)
