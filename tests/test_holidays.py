from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from notibondi.holidays import load_holidays
from notibondi.schedules import (
    BUENOS_AIRES,
    HOLIDAY_SERVICE,
    next_arrivals,
    service_for,
)

# Every test inserts its own holidays on the test connection, which rolls
# back when the connection closes: nothing leaks into other tests.

PLAZA_ITALIA = "6490106165"
REPO_HOLIDAYS = Path(__file__).parent.parent / "holidays.csv"

MONDAY, TUESDAY, WEDNESDAY = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11)


def add_holiday(conn: Connection, day: date, name: str = "Feriado de prueba") -> None:
    conn.execute(
        text("INSERT INTO holidays (holiday_date, name) VALUES (:day, :name)"),
        {"day": day, "name": name},
    )


def holidays_in_db(conn: Connection) -> list[tuple[date, str]]:
    return conn.execute(
        text("SELECT holiday_date, name FROM holidays ORDER BY holiday_date")
    ).all()


def write_csv(path: Path, *lines: str) -> Path:
    path.write_text("\n".join(["date,name", *lines]) + "\n", encoding="utf-8")
    return path


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=BUENOS_AIRES)


# service_for


def test_service_for_a_holiday_is_the_holiday_service(conn):
    assert service_for(conn, TUESDAY) == "1"

    add_holiday(conn, TUESDAY)

    assert service_for(conn, TUESDAY) == HOLIDAY_SERVICE == "3"


def test_service_for_a_holiday_on_a_weekday_without_service(conn):
    # The fixture has no Wednesdays, but a holiday doesn't need the weekday
    add_holiday(conn, WEDNESDAY)

    assert service_for(conn, WEDNESDAY) == "3"


def test_service_for_only_the_holiday_itself_changes(conn):
    add_holiday(conn, MONDAY)

    assert service_for(conn, MONDAY) == "3"
    assert service_for(conn, TUESDAY) == "1"
    # Same weekday a week later is a regular Monday
    assert service_for(conn, date(2026, 11, 16)) == "1"


# next_arrivals


def test_next_arrivals_on_a_holiday_uses_the_holiday_service(conn):
    # Trip 1-1 (service 1) passes at 08:05 on a regular Tuesday; the fixture
    # has no service 3 trips, so on a holiday nothing comes
    assert next_arrivals(conn, PLAZA_ITALIA, at(TUESDAY, 8)) != []

    add_holiday(conn, TUESDAY)

    assert next_arrivals(conn, PLAZA_ITALIA, at(TUESDAY, 8)) == []


def test_next_arrivals_after_midnight_uses_yesterdays_holiday_service(conn):
    # Wednesday 00:30 normally shows Tuesday's 24:40:00 trip of service 1.
    # If Tuesday was a holiday, yesterday's service is 3 and it's gone.
    assert [
        a.minutes for a in next_arrivals(conn, PLAZA_ITALIA, at(WEDNESDAY, 0, 30))
    ] == [10]

    add_holiday(conn, TUESDAY)

    assert next_arrivals(conn, PLAZA_ITALIA, at(WEDNESDAY, 0, 30)) == []


def test_next_arrivals_on_a_holiday_keeps_yesterdays_late_trips(conn):
    # A holiday Wednesday doesn't touch Tuesday's regular late trip
    add_holiday(conn, WEDNESDAY)

    assert [
        a.minutes for a in next_arrivals(conn, PLAZA_ITALIA, at(WEDNESDAY, 0, 30))
    ] == [10]


# load_holidays


def test_load_holidays_loads_the_csv(conn, tmp_path):
    path = write_csv(tmp_path / "h.csv", "2026-12-08,Inmaculada", "2026-12-25,Navidad")

    assert load_holidays(conn, path) == 2
    assert holidays_in_db(conn) == [
        (date(2026, 12, 8), "Inmaculada"),
        (date(2026, 12, 25), "Navidad"),
    ]


def test_load_holidays_twice_does_not_duplicate(conn, tmp_path):
    path = write_csv(tmp_path / "h.csv", "2026-12-25,Navidad")

    load_holidays(conn, path)
    load_holidays(conn, path)

    assert holidays_in_db(conn) == [(date(2026, 12, 25), "Navidad")]


def test_load_holidays_replaces_what_was_there(conn, tmp_path):
    # A date removed from the CSV stops being a holiday
    add_holiday(conn, TUESDAY)

    load_holidays(conn, write_csv(tmp_path / "h.csv", "2026-12-25,Navidad"))

    assert holidays_in_db(conn) == [(date(2026, 12, 25), "Navidad")]
    assert service_for(conn, TUESDAY) == "1"


def test_load_holidays_with_an_empty_csv_clears_the_table(conn, tmp_path):
    add_holiday(conn, TUESDAY)

    assert load_holidays(conn, write_csv(tmp_path / "h.csv")) == 0
    assert holidays_in_db(conn) == []


def test_load_holidays_reads_utf8_names(conn, tmp_path):
    load_holidays(conn, write_csv(tmp_path / "h.csv", "2027-01-01,Año Nuevo"))

    assert holidays_in_db(conn) == [(date(2027, 1, 1), "Año Nuevo")]


def test_load_holidays_rejects_a_bad_date(conn, tmp_path):
    with pytest.raises(ValueError):
        load_holidays(conn, write_csv(tmp_path / "h.csv", "25/12/2026,Navidad"))


def test_the_repo_holidays_csv_loads(conn):
    # Guards the hand-edited file: valid dates, no repeats (the PK would fail)
    count = load_holidays(conn, REPO_HOLIDAYS)

    assert count > 0
    assert len(holidays_in_db(conn)) == count
