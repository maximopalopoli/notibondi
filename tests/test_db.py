import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError

from notibondi.db import POOL_TIMEOUT_S, without_timeout


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


def test_a_failed_query_doesnt_show_its_parameters(db_engine):
    # The traceback goes to the log, and the parameters are often where
    # the user is
    with db_engine.connect() as conn, pytest.raises(DBAPIError) as error:
        conn.execute(text("SELECT CAST(:lat AS float) / 0"), {"lat": -34.6037})

    assert "division by zero" in str(error.value)
    assert "-34.6037" not in str(error.value)


def test_a_request_waits_little_for_a_free_connection(db_engine):
    assert db_engine.pool.timeout() == POOL_TIMEOUT_S <= 5


# The app role: reads everything, writes only route_names


def test_the_app_role_reads_the_tables(app_engine, gtfs_loaded):
    with app_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM stops")).scalar() > 0
        assert conn.execute(text("SELECT current_user")).scalar() == "notibondi_app"


def test_the_app_role_saves_route_names(app_engine):
    with app_engine.connect() as conn:
        for _ in range(2):  # the second time is the UPDATE of the upsert
            conn.execute(
                text("""
                    INSERT INTO route_names (route_id, name, seen_at)
                    VALUES ('test-route', '999A', now())
                    ON CONFLICT (route_id) DO UPDATE SET name = EXCLUDED.name
                """)
            )
        conn.rollback()


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM stops",
        "UPDATE routes SET route_short_name = 'x'",
        "INSERT INTO holidays (holiday_date, name) VALUES ('2030-01-01', 'x')",
        "DELETE FROM route_names",
        "TRUNCATE route_names",
        "CREATE TABLE intruder (id int)",
        "DROP TABLE stops",
        "COPY (SELECT 1) TO PROGRAM 'id'",
        "SELECT pg_read_file('/etc/passwd')",
    ],
)
def test_the_app_role_cant_change_anything_else(app_engine, statement):
    with (
        app_engine.connect() as conn,
        pytest.raises(ProgrammingError, match="denied|must be owner"),
    ):
        conn.execute(text(statement))
