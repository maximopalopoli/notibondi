import csv
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import Connection, text

from notibondi.db import get_engine


def load_holidays(conn: Connection, path: Path) -> int:
    """Replace the holidays table with the dates in a `date,name` CSV."""
    with path.open(encoding="utf-8", newline="") as f:
        rows = [
            {"holiday_date": date.fromisoformat(row["date"]), "name": row["name"]}
            for row in csv.DictReader(f)
        ]
    conn.execute(text("DELETE FROM holidays"))
    if rows:
        conn.execute(
            text(
                "INSERT INTO holidays (holiday_date, name) VALUES (:holiday_date, :name)"
            ),
            rows,
        )
    return len(rows)


if __name__ == "__main__":
    with get_engine().begin() as conn:
        count = load_holidays(conn, Path(sys.argv[1]))
    print(f"Loaded {count} holidays")
