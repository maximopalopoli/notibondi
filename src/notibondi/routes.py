from pydantic import BaseModel
from sqlalchemy import Connection, text


class Route(BaseModel):
    route_id: str
    route_short_name: str
    route_desc: str


def search_routes(conn: Connection, q: str) -> list[Route]:
    rows = conn.execute(
        text(
            """
            SELECT route_id, route_short_name, route_desc
            FROM routes
            WHERE route_short_name ~* :pattern
            ORDER BY route_short_name
        """
        ),
        # The endpoint only lets letters and digits in, so q can't add regex
        # syntax. [^0-9] stops "15" from matching 152A.
        {"pattern": f"^{q}([^0-9]|$)"},
    )
    return [Route(**row._mapping) for row in rows]
