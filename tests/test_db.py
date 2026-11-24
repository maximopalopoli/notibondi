import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from notibondi.db import without_timeout


def test_test_database_has_postgis(db_engine):
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
        # This confirms migrations had been run
        assert conn.execute(text("SELECT postgis_version()")).scalar()


def test_a_query_too_slow_is_cancelled(db_engine):
    with db_engine.connect() as conn:
        conn.execute(text("SET statement_timeout = '50ms'"))
        with pytest.raises(OperationalError, match="statement timeout"):
            conn.execute(text("SELECT pg_sleep(1)"))


def test_connections_start_with_the_limit(db_engine):
    with db_engine.connect() as conn:
        assert conn.execute(text("SHOW statement_timeout")).scalar() == "5s"


def test_a_script_can_lift_the_limit_for_its_transaction(db_engine):
    with db_engine.begin() as conn:
        without_timeout(conn)
        assert conn.execute(text("SHOW statement_timeout")).scalar() == "0"
    with db_engine.connect() as conn:
        assert conn.execute(text("SHOW statement_timeout")).scalar() == "5s"
