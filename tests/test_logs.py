import logging

import pytest

from notibondi.main import DropQueryString

ACCESS = '%s - "%s %s HTTP/%s" %d'


@pytest.fixture
def access_log(caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.access")
    return logging.getLogger("uvicorn.access")


def test_the_access_log_keeps_the_path_but_not_the_location(access_log, caplog):
    access_log.info(
        ACCESS,
        "1.2.3.4",
        "GET",
        "/partials/stops?lat=-34.6037&lon=-58.3816",
        "1.1",
        200,
    )

    assert '"GET /partials/stops HTTP/1.1" 200' in caplog.text
    assert "34.6037" not in caplog.text


def test_the_access_log_drops_the_typed_address(access_log, caplog):
    access_log.info(
        ACCESS,
        "1.2.3.4",
        "GET",
        "/partials/stops/address?q=Triunvirato+3424",
        "1.1",
        200,
    )

    assert "Triunvirato" not in caplog.text
    assert "/partials/stops/address" in caplog.text


def test_other_log_lines_pass_untouched():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "%s?%s", ("a", "b"), None
    )

    assert DropQueryString().filter(record)
    assert record.getMessage() == "a?b"
