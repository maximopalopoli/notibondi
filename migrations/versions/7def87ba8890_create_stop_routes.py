"""create stop routes

Revision ID: 7def87ba8890
Revises: a5482976feec
Create Date: 2026-11-03 13:47:01.547014

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7def87ba8890"
down_revision: str | Sequence[str] | None = "a5482976feec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE TABLE stop_routes (
            stop_id TEXT NOT NULL,
            route_id TEXT NOT NULL,
            PRIMARY KEY (stop_id, route_id)
        )
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE stop_routes")
