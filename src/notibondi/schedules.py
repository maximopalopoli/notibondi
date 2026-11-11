from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import Connection, text

BUENOS_AIRES = ZoneInfo("America/Argentina/Buenos_Aires")


def now(tz: ZoneInfo = BUENOS_AIRES) -> datetime:
    return datetime.now(tz)


class Arrival(BaseModel):
    line: str
    headsign: str
    minutes: int
    source: Literal["scheduled"] = "scheduled"


def to_gtfs_time(seconds: int) -> str:
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def from_gtfs_time(value: str) -> int:
    h, m, s = (int(part) for part in value.split(":"))
    return h * 3600 + m * 60 + s


def next_arrivals(conn: Connection, stop_id: str, at: datetime) -> list[Arrival]:
    service = service_for(conn, at.date())
    if service is None:
        return []

    start = at.hour * 3600 + at.minute * 60 + at.second
    end = start + 90 * 60

    rows = conn.execute(
        text("""
            SELECT r.route_short_name AS line, t.trip_headsign AS headsign, st.arrival_time
            FROM stop_times st
            JOIN trips t ON t.trip_id = st.trip_id
            JOIN routes r ON r.route_id = t.route_id
            WHERE st.stop_id = :stop_id
            AND t.service_id = :service_id
            AND st.arrival_time >= :start AND st.arrival_time < :end
            ORDER BY st.arrival_time, r.route_short_name
            LIMIT 20
        """),
        {
            "stop_id": stop_id,
            "service_id": service,
            "start": to_gtfs_time(start),
            "end": to_gtfs_time(end),
        },
    )

    return [
        Arrival(
            line=row.line,
            headsign=row.headsign,
            minutes=(from_gtfs_time(row.arrival_time) - start) // 60,
        )
        for row in rows
    ]


def service_for(conn: Connection, day: date) -> str | None:
    """Return the service that runs on the same weekday as `day`.

    The feed's calendar only covers late 2019, so the date itself is never
    in it. Instead, pick the service most often used on that weekday there;
    holidays and odd days lose to the regular one. None if no date in the
    calendar falls on that weekday.
    """
    return conn.execute(
        text("""
            SELECT service_id
            FROM calendar_dates
            WHERE exception_type = 1
            AND EXTRACT(DOW FROM service_date) = EXTRACT(DOW FROM CAST(:day AS date))
            GROUP BY service_id
            ORDER BY count(*) DESC, service_id
            LIMIT 1
        """),
        {"day": day},
    ).scalar()
