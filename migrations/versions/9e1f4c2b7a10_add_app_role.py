"""add the app role: reads everything, writes only route_names

Revision ID: 9e1f4c2b7a10
Revises: 3c2e7a91d4f0
Create Date: 2026-11-24 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9e1f4c2b7a10"
down_revision: str | Sequence[str] | None = "3c2e7a91d4f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same name as notibondi.db.APP_ROLE. Migrations don't import the app, so a
# rename later doesn't change what an old migration did
APP_ROLE = "notibondi_app"


def upgrade() -> None:
    # Roles belong to the whole server, not to one database: the dev and the
    # test database share it, so it may exist already. NOLOGIN until
    # `make app-role` gives it the password from DATABASE_URL
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN;
            END IF;
        END
        $$
    """)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    # The names of the live feed (realtime.save_route_names), an upsert
    op.execute(f"GRANT INSERT, UPDATE ON route_names TO {APP_ROLE}")
    # Tables that later migrations create: readable without another GRANT
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM {APP_ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    # The role stays: another database of the same server may still use it
