from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import Connection, text

DAY_SECONDS = 24 * 3600
WINDOW_SECONDS = 90 * 60

# Yesterday's trips count until 30:00:00 (06:00 today); later times in the
# feed are broken trips that would show up as phantom arrivals.
MAX_SERVICE_SECONDS = 30 * 3600
# Per branch: more of the same line only push the other lines down
MAX_PER_LINE = 3

# In the 2021 feed (/colectivos/feed-gtfs) the holidays run service 3. The
# 2019 one used 4, which in 2021 is Sunday: the importer checks this number
# against the calendar (check_holiday_service).
HOLIDAY_SERVICE = "3"

BUENOS_AIRES = ZoneInfo("America/Argentina/Buenos_Aires")


def now(tz: ZoneInfo = BUENOS_AIRES) -> datetime:
    return datetime.now(tz)


class Arrival(BaseModel):
    line: str
    headsign: str
    minutes: int
    source: Literal["scheduled", "realtime"] = "scheduled"
    # The GTFS direction, for the line's ☆ (a favorite line is a line and a
    # direction). None when the schedule doesn't say (a live-only line)
    direction_id: int | None = None
    # False: a live bus of this number ("152"), branch unknown
    branch_known: bool = True


def to_gtfs_time(seconds: int) -> str:
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def from_gtfs_time(value: str) -> int:
    h, m, s = (int(part) for part in value.split(":"))
    return h * 3600 + m * 60 + s


def _arrivals_in_service(
    conn: Connection,
    stop_id: str,
    service_id: str,
    start: int,
    end: int,
    line: str | None = None,
) -> list[tuple[int, str, str, int]]:
    """(seconds until arrival, line, headsign, direction_id) for one service
    and window, of every line or only of `line`."""
    rows = conn.execute(
        text("""
            SELECT line, headsign, direction_id, arrival_time
            FROM (
                SELECT r.route_short_name AS line, t.trip_headsign AS headsign,
                    t.direction_id, st.arrival_time,
                    row_number() OVER (
                        PARTITION BY r.route_short_name ORDER BY st.arrival_time
                    ) AS n
                FROM stop_times st
                JOIN trips t ON t.trip_id = st.trip_id
                JOIN routes r ON r.route_id = t.route_id
                WHERE st.stop_id = :stop_id
                AND t.service_id = :service_id
                AND st.arrival_time >= :start AND st.arrival_time < :end
                AND (CAST(:line AS text) IS NULL OR r.route_short_name = :line)
            ) ranked
            WHERE n <= :per_line
            ORDER BY arrival_time, line
        """),
        {
            "stop_id": stop_id,
            "service_id": service_id,
            "start": to_gtfs_time(start),
            "end": to_gtfs_time(end),
            "per_line": MAX_PER_LINE,
            "line": line,
        },
    )
    return [
        (
            from_gtfs_time(row.arrival_time) - start,
            row.line,
            row.headsign,
            row.direction_id,
        )
        for row in rows
    ]


def next_arrivals(
    conn: Connection, stop_id: str, at: datetime, line: str | None = None
) -> list[Arrival]:
    """Scheduled arrivals in the next 90 minutes, of every line or only of
    `line` (filtered before the limit, so a busy stop doesn't hide it).

    Trips belong to the service day they start on, so after midnight the
    buses of yesterday's service still running show up as 24:xx:xx times.
    """
    at = at.astimezone(BUENOS_AIRES)
    today = at.date()
    start = at.hour * 3600 + at.minute * 60 + at.second
    end = start + WINDOW_SECONDS

    found = []

    service = service_for(conn, today)
    if service is not None:
        found += _arrivals_in_service(conn, stop_id, service, start, end, line)

    yesterday_start = start + DAY_SECONDS
    yesterday_end = min(end + DAY_SECONDS, MAX_SERVICE_SECONDS)
    if yesterday_start < yesterday_end:
        service = service_for(conn, today - timedelta(days=1))
        if service is not None:
            found += _arrivals_in_service(
                conn, stop_id, service, yesterday_start, yesterday_end, line
            )

    found.sort()
    return first_per_line(
        [
            Arrival(
                line=line,
                headsign=headsign,
                minutes=seconds // 60,
                direction_id=direction_id,
            )
            for seconds, line, headsign, direction_id in found
        ]
    )


def first_per_line(arrivals: list[Arrival]) -> list[Arrival]:
    """The first MAX_PER_LINE arrivals of each line, keeping their order
    (sorted by time, they are the soonest)."""
    seen: dict[str, int] = {}
    kept = []
    for a in arrivals:
        seen[a.line] = seen.get(a.line, 0) + 1
        if seen[a.line] <= MAX_PER_LINE:
            kept.append(a)
    return kept


def service_for(conn: Connection, day: date) -> str | None:
    """Return the service that runs on `day`.

    Holidays, loaded by hand into the holidays table, run HOLIDAY_SERVICE.
    Any other day gets the service most often used on its weekday in the
    feed's calendar, which only covers the first half of 2021, so the date
    itself is never in it. None if no date in the calendar falls on that weekday.
    """
    is_holiday = conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM holidays WHERE holiday_date = :day)"),
        {"day": day},
    ).scalar()
    if is_holiday:
        return HOLIDAY_SERVICE
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
