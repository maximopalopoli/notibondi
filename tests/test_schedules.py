from datetime import date

import pytest

from notibondi.schedules import service_for

# 2026 dates are not in the 2019 fixture calendar: the service has to come
# from the day of the week, not from the date itself.


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        # Fixture Tuesdays: two with service 3, and 2019-12-24 with service 1
        (date(2026, 11, 10), "3"),  # Tuesday
        (date(2026, 11, 14), "1"),  # Saturday
        (date(2026, 11, 15), "2"),  # Sunday
    ],
)
def test_service_for_uses_the_most_common_service_of_the_weekday(conn, day, expected):
    assert service_for(conn, day) == expected


def test_service_for_is_not_fooled_by_a_holiday(conn):
    # Fixture Mondays: two with service 3, and the 2019-11-18 holiday with 4
    assert service_for(conn, date(2026, 11, 9)) == "3"


def test_service_for_a_date_in_the_calendar_still_goes_by_weekday(conn):
    # 2019-12-24 itself ran service 1, but it was a Tuesday like most with 3
    assert service_for(conn, date(2019, 12, 24)) == "3"


def test_service_for_returns_none_without_dates_for_that_weekday(conn):
    # The fixture has no Wednesdays
    assert service_for(conn, date(2026, 11, 11)) is None
