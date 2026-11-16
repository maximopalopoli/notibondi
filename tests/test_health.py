import time

import pytest
from fastapi.testclient import TestClient

from notibondi.main import app, get_live
from notibondi.worker import MAX_FEED_AGE_SECONDS, LiveFeed, feed_health


def fetched_ago(seconds: float) -> LiveFeed:
    return LiveFeed(fetched_at=time.monotonic() - seconds)


@pytest.fixture
def client_with_live():
    """A TestClient whose /health sees the LiveFeed the test gives it."""

    def make(live: LiveFeed) -> TestClient:
        app.dependency_overrides[get_live] = lambda: live
        return TestClient(app)

    yield make
    app.dependency_overrides.pop(get_live, None)


# feed_health


def test_a_fresh_feed_is_ok():
    health = feed_health(fetched_ago(42.4))

    assert health.status == "ok"
    assert health.feed_age_seconds == 42


def test_an_old_feed_is_degraded():
    health = feed_health(fetched_ago(MAX_FEED_AGE_SECONDS + 1))

    assert health.status == "degraded"
    assert health.feed_age_seconds == MAX_FEED_AGE_SECONDS + 1


def test_a_feed_right_at_the_limit_is_still_ok():
    # A few ms pass between fetched_ago() and feed_health(), so aim just below.
    health = feed_health(fetched_ago(MAX_FEED_AGE_SECONDS - 0.5))

    assert health.status == "ok"


def test_no_feed_yet_is_degraded_with_no_age():
    health = feed_health(LiveFeed())

    assert health.status == "degraded"
    assert health.feed_age_seconds is None


def test_the_age_is_a_whole_number_of_seconds():
    assert isinstance(feed_health(fetched_ago(12.9)).feed_age_seconds, int)


# GET /health


def test_health_endpoint_reports_a_fresh_feed(client_with_live):
    response = client_with_live(fetched_ago(10)).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "feed_age_seconds": 10,
        "vehicles_age_seconds": None,
    }


def test_health_endpoint_stays_200_when_degraded(client_with_live):
    # Degraded means "no live data", not "the app is down": still 200.
    response = client_with_live(LiveFeed()).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "feed_age_seconds": None,
        "vehicles_age_seconds": None,
    }


def test_health_is_registered_once():
    paths = [route.path for route in app.routes if route.path == "/health"]
    assert paths == ["/health"]


def test_the_positions_age_is_reported():
    live = LiveFeed(fetched_at=time.monotonic(), vehicles_at=time.monotonic() - 30.6)

    assert feed_health(live).vehicles_age_seconds == 30


def test_no_positions_yet_has_no_age():
    assert feed_health(fetched_ago(10)).vehicles_age_seconds is None


def test_old_positions_do_not_make_the_app_degraded():
    # The map gets worse, but the arrivals still work
    live = LiveFeed(
        fetched_at=time.monotonic(),
        vehicles_at=time.monotonic() - MAX_FEED_AGE_SECONDS * 10,
    )

    assert feed_health(live).status == "ok"
