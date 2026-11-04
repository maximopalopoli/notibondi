import pytest
from sqlalchemy import text

from notibondi.importer import import_gtfs


def test_import_loads_all_stops(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        count = conn.execute(text("SELECT count(*) FROM stops")).scalar()

        assert count == 4
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

        assert count == 4
        conn.rollback()


def test_import_loads_routes_and_trips(db_engine, gtfs_zip):
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)

        routes = conn.execute(text("SELECT count(*) FROM routes")).scalar()
        trips = conn.execute(text("SELECT count(*) FROM trips")).scalar()

        assert routes == 2
        assert trips == 4
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

        assert count == 10
        conn.rollback()


def test_import_twice_does_not_duplicate_stop_times(db_engine, gtfs_zip):
    # stop_times has no primary key, so a missing TRUNCATE would duplicate
    # rows silently instead of failing
    with db_engine.connect() as conn:
        import_gtfs(conn, gtfs_zip)
        import_gtfs(conn, gtfs_zip)

        count = conn.execute(text("SELECT count(*) FROM stop_times")).scalar()

        assert count == 10
        conn.rollback()


def test_import_builds_one_stop_route_per_pair(db_engine, gtfs_zip):
    # The fixture has 10 stop_times but only 5 distinct (stop, route) pairs
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
