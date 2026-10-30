import csv
import io
import sys
import time
import zipfile
from pathlib import Path

from sqlalchemy import Connection, text

from notibondi.db import get_engine


def import_gtfs(conn: Connection, zip_path: Path) -> None:
    """Load the GTFS zip into the database. The caller owns the transaction."""

    conn.execute(text("TRUNCATE stops"))
    with zipfile.ZipFile(zip_path) as zf, zf.open("stops.txt") as raw:
        text_file = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        reader = csv.DictReader(text_file)

        rows = [
            {
                "stop_id": row["stop_id"],
                "stop_name": row["stop_name"],
                "lat": float(row["stop_lat"]),
                "lon": float(row["stop_lon"]),
            }
            for row in reader
        ]

        conn.execute(
            text("""
                INSERT INTO stops (stop_id, stop_name, geom)
                VALUES (
                    :stop_id,
                    :stop_name,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                )
            """),
            rows,
        )

    conn.execute(text("ANALYZE stops"))


if __name__ == "__main__":
    path = Path(sys.argv[1])

    start = time.perf_counter()
    with get_engine().begin() as conn:
        import_gtfs(conn, path)

    end = time.perf_counter()

    print(f"Time spent to import: {end - start:.2f} seconds")
