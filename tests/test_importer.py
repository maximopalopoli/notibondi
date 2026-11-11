from datetime import date

import pytest
from sqlalchemy import text

from notibondi.importer import import_gtfs


def test_import_loads_all_stops(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        count = conn.execute(text("SELECT count(*) FROM stops")).scalar()

        assert count == 5
        conn.rollback()


def test_import_stores_stop_position(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        lat, lon = conn.execute(
            text("""
                SELECT ST_Y(geom::geometry), ST_X(geom::geometry)
                FROM stops
                WHERE stop_id = '6490106165'
            """)
        ).one()

        assert lat == pytest.approx(-34.581)
        assert lon == pytest.approx(-58.421)
        conn.rollback()


def test_import_twice_does_not_duplicate_stops(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)
        import_gtfs(conn, gtfs_zip)

        count = conn.execute(text("SELECT count(*) FROM stops")).scalar()

        assert count == 5
        conn.rollback()


def test_import_loads_routes_and_trips(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        routes = conn.execute(text("SELECT count(*) FROM routes")).scalar()
        trips = conn.execute(text("SELECT count(*) FROM trips")).scalar()

        assert routes == 2
        assert trips == 5
        conn.rollback()


def test_import_links_trips_to_their_route(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        line = conn.execute(
            text("""
                SELECT r.route_short_name
                FROM trips t
                JOIN routes r ON r.route_id = t.route_id
                WHERE t.trip_id = '3-1'
            """)
        ).scalar_one()

        assert line == "505R3"
        conn.rollback()


def test_import_loads_stop_times(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        count = conn.execute(text("SELECT count(*) FROM stop_times")).scalar()

        assert count == 11
        conn.rollback()


def test_import_twice_does_not_duplicate_stop_times(db_engine, gtfs_zip):
    # stop_times has no primary key, so a missing TRUNCATE would duplicate
    # rows silently instead of failing
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)
        import_gtfs(conn, gtfs_zip)

        count = conn.execute(text("SELECT count(*) FROM stop_times")).scalar()

        assert count == 11
        conn.rollback()


def test_import_builds_one_stop_route_per_pair(db_engine, gtfs_zip):
    # The fixture has 11 stop_times but only 5 distinct (stop, route) pairs
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        count = conn.execute(text("SELECT count(*) FROM stop_routes")).scalar()

        assert count == 5
        conn.rollback()


def test_import_lists_every_route_of_a_stop(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        lines = (
            conn.execute(
                text("""
                SELECT r.route_short_name
                FROM stop_routes sr
                JOIN routes r ON r.route_id = sr.route_id
                WHERE sr.stop_id = '6490106165'
                ORDER BY r.route_short_name
            """)
            )
            .scalars()
            .all()
        )

        assert lines == ["152A", "505R3"]
        conn.rollback()


def test_import_stores_service_and_headsign_of_trips(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        trips = conn.execute(
            text("""
                SELECT trip_id, service_id, trip_headsign
                FROM trips
                ORDER BY trip_id
            """)
        ).all()

        assert [tuple(t) for t in trips] == [
            ("1-1", "3", "a Olivos"),
            ("2-1", "1", "a Olivos"),
            ("3-1", "3", "a Merlo"),
            ("4-1", "3", "a Merlo"),
            ("5-1", "3", "a Merlo"),
        ]
        conn.rollback()


def test_import_stores_arrival_times(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        times = (
            conn.execute(
                text("""
                SELECT arrival_time
                FROM stop_times
                WHERE trip_id = '1-1'
                ORDER BY arrival_time
            """)
            )
            .scalars()
            .all()
        )

        assert times == ["07:58:00", "08:05:00", "08:20:00"]
        conn.rollback()


def test_import_keeps_arrival_times_past_midnight(db_engine, gtfs_zip):
    # GTFS allows hours above 24 for trips of a service day that end
    # after midnight; they must be stored as written
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        arrival = conn.execute(
            text("""
                SELECT arrival_time
                FROM stop_times
                WHERE trip_id = '4-1' AND stop_id = '6490106165'
            """)
        ).scalar_one()

        assert arrival == "24:40:00"
        conn.rollback()


def test_import_fills_every_new_column(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        nulls = conn.execute(
            text("""
                SELECT
                    (SELECT count(*) FROM stop_times WHERE arrival_time IS NULL),
                    (SELECT count(*) FROM trips WHERE service_id IS NULL),
                    (SELECT count(*) FROM trips WHERE trip_headsign IS NULL)
            """)
        ).one()

        assert tuple(nulls) == (0, 0, 0)
        conn.rollback()


def test_import_loads_calendar_dates(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        count = conn.execute(text("SELECT count(*) FROM calendar_dates")).scalar()

        assert count == 10
        conn.rollback()


def test_import_parses_calendar_dates_as_dates(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        row = conn.execute(
            text("""
                SELECT service_date, exception_type
                FROM calendar_dates
                WHERE service_id = '1'
                ORDER BY service_date DESC
                LIMIT 1
            """)
        ).one()

        assert row.service_date == date(2019, 12, 24)
        assert row.exception_type == 1
        conn.rollback()


def test_import_twice_does_not_duplicate_calendar_dates(db_engine, gtfs_zip):
    # Without the TRUNCATE the second import would hit the primary key
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)
        import_gtfs(conn, gtfs_zip)

        count = conn.execute(text("SELECT count(*) FROM calendar_dates")).scalar()

        assert count == 10
        conn.rollback()
