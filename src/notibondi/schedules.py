from datetime import date

from sqlalchemy import Connection, text


def service_for(conn: Connection, day: date) -> str | None:
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
