from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Connection, Engine, create_engine, text

from notibondi.config import get_settings


def get_conn() -> Iterator[Connection]:
    with get_engine().connect() as conn:
        yield conn


Conn = Annotated[Connection, Depends(get_conn)]

# The slowest page query takes ~0.3 s (the stop lookups at startup). One that
# runs longer is a bug or an abuse, and left alone it would keep a connection
# and a thread busy: Postgres cancels it, and the request fails
STATEMENT_TIMEOUT = "5s"


def make_engine(url: str) -> Engine:
    return create_engine(
        url, connect_args={"options": f"-c statement_timeout={STATEMENT_TIMEOUT}"}
    )


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


def without_timeout(conn: Connection) -> None:
    """Lift the limit for the rest of this transaction, for scripts that
    load data for minutes (the GTFS import), not for pages."""
    conn.execute(text("SET LOCAL statement_timeout = 0"))


# For a route that must not hold a connection the whole time (it waits on
# something else first): it opens one itself, only when it needs it
DbEngine = Annotated[Engine, Depends(get_engine)]
