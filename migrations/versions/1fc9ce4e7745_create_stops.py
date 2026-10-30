"""create stops

Revision ID: 1fc9ce4e7745
Revises: 528efbe95916
Create Date: 2026-10-29 11:25:52.607196

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1fc9ce4e7745"
down_revision: str | Sequence[str] | None = "528efbe95916"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE TABLE stops (
            stop_id TEXT PRIMARY KEY,
            stop_name TEXT NOT NULL,
            geom geography(Point, 4326) NOT NULL
        )
    """)
    op.execute("CREATE INDEX stops_geom_idx ON stops USING GIST (geom)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE stops")
