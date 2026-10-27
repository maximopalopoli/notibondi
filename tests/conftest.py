import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url

from notibondi.config import get_settings


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
