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

# The role the app connects as (the add_app_role migration): it can read
# every table and write only route_names, so a bug that runs SQL it shouldn't
# can't change the data, create tables or reach the server's files
APP_ROLE = "notibondi_app"

# The slowest page query takes ~0.3 s (the stop lookups at startup). One that
# runs longer is a bug or an abuse, and left alone it would keep a connection
# and a thread busy: Postgres cancels it, and the request fails
STATEMENT_TIMEOUT = "5s"


# With every connection busy, a request waits this long for one and fails.
# SQLAlchemy's default is 30 s: under a flood the waiting requests keep a
# thread each, and the pages that don't need the database stop answering too
POOL_TIMEOUT_S = 3


def make_engine(url: str, role: str | None = None) -> Engine:
    """role: connect as the owner but act as that role (the tests, that
    use one login for everything)."""
    options = f"-c statement_timeout={STATEMENT_TIMEOUT}"
    if role:
        options += f" -c role={role}"
    return create_engine(
        url,
        # A failed query's error carries its parameters, and the traceback
        # goes to the log: they'd leak where the user is (lat, lon)
        hide_parameters=True,
        pool_timeout=POOL_TIMEOUT_S,
        connect_args={"options": options},
    )


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


@lru_cache
def get_admin_engine() -> Engine:
    """The owner's engine, for the scripts that load data."""
    settings = get_settings()
    return make_engine(settings.admin_database_url or settings.database_url)


def without_timeout(conn: Connection) -> None:
    """Lift the limit for the rest of this transaction, for scripts that
    load data for minutes (the GTFS import), not for pages."""
    conn.execute(text("SET LOCAL statement_timeout = 0"))


# For a route that must not hold a connection the whole time (it waits on
# something else first): it opens one itself, only when it needs it
DbEngine = Annotated[Engine, Depends(get_engine)]
