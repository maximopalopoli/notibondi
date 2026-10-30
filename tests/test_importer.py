import shutil
from pathlib import Path

import pytest
from sqlalchemy import text

from notibondi.importer import import_gtfs

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "gtfs-mini"


@pytest.fixture
def gtfs_zip(tmp_path):
    """Zip the mini GTFS fixture and return the path to the archive."""
    archive = shutil.make_archive(str(tmp_path / "gtfs"), "zip", root_dir=FIXTURE_DIR)
    return Path(archive)


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
