import shutil
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url

from notibondi.config import get_settings
from notibondi.db import get_conn
from notibondi.importer import import_gtfs
from notibondi.main import app

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "gtfs-mini"


@pytest.fixture(scope="session")
def db_engine():
    url = make_url(get_settings().database_url)
    test_url = url.set(database="notibondi_test")
    test_url_str = test_url.render_as_string(hide_password=False)

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", test_url_str)
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(test_url)
    yield engine

    engine.dispose()
    command.downgrade(alembic_cfg, "base")


@pytest.fixture(scope="session")
def gtfs_loaded(db_engine, gtfs_zip):
    with db_engine.begin() as conn:
        import_gtfs(conn, gtfs_zip)


@pytest.fixture(scope="session")
def gtfs_zip(tmp_path_factory):
    base = tmp_path_factory.mktemp("gtfs") / "gtfs-mini"
    return shutil.make_archive(str(base), "zip", FIXTURE_DIR)


@pytest.fixture
def conn(db_engine, gtfs_loaded):
    with db_engine.connect() as conn:
        yield conn


@pytest.fixture
def client(db_engine, gtfs_loaded):
    def override():
        with db_engine.connect() as conn:
            yield conn

    app.dependency_overrides[get_conn] = override
    yield TestClient(app)
    app.dependency_overrides.clear()
