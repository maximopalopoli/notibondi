from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Connection, Engine, create_engine

from notibondi.config import get_settings


def get_conn() -> Iterator[Connection]:
    with get_engine().connect() as conn:
        yield conn


Conn = Annotated[Connection, Depends(get_conn)]


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url)


# For a route that must not hold a connection the whole time (it waits on
# something else first): it opens one itself, only when it needs it
DbEngine = Annotated[Engine, Depends(get_engine)]
