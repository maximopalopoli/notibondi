from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, text

BUENOS_AIRES = ZoneInfo("America/Argentina/Buenos_Aires")


def now(tz: ZoneInfo = BUENOS_AIRES) -> datetime:
    return datetime.now(tz)


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
