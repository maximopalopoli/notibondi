"""Let the app role log in, with the password in DATABASE_URL.

The migration creates the role without login, because a password doesn't
belong in git. This runs as the owner (ADMIN_DATABASE_URL) and is safe to
run again, for example after changing the password.
"""

from psycopg import sql
from sqlalchemy import make_url

from notibondi.config import get_settings
from notibondi.db import APP_ROLE, get_admin_engine


def main() -> None:
    url = make_url(get_settings().database_url)
    if url.username != APP_ROLE:
        print(f"DATABASE_URL connects as {url.username}, not {APP_ROLE}: nothing to do")
        return
    if not url.password:
        raise SystemExit(f"DATABASE_URL has no password for {APP_ROLE}")
    statement = sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
        sql.Identifier(APP_ROLE), sql.Literal(url.password)
    )
    with get_admin_engine().begin() as conn:
        # ALTER ROLE takes no bind parameters: psycopg quotes the literal
        conn.exec_driver_sql(statement.as_string(conn.connection.driver_connection))
    print(f"{APP_ROLE} can log in now")


if __name__ == "__main__":
    main()
