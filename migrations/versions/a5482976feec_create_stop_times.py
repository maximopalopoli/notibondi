"""create stop times

Revision ID: a5482976feec
Revises: bb5a35d46652
Create Date: 2026-11-03 12:17:24.408981

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5482976feec"
down_revision: str | Sequence[str] | None = "bb5a35d46652"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE TABLE stop_times (
            trip_id TEXT NOT NULL,
            stop_id TEXT NOT NULL
        )
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE stop_times")
