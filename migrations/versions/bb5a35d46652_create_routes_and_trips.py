"""create routes and trips

Revision ID: bb5a35d46652
Revises: 1fc9ce4e7745
Create Date: 2026-11-03 11:54:01.137201

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bb5a35d46652"
down_revision: str | Sequence[str] | None = "1fc9ce4e7745"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE TABLE routes (
            route_id TEXT PRIMARY KEY,
            route_short_name TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE trips (
            trip_id TEXT PRIMARY KEY,
            route_id TEXT NOT NULL REFERENCES routes (route_id)
        )
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE trips")
    op.execute("DROP TABLE routes")
