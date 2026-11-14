"""add route_desc for routes

Revision ID: bd33bf39edf6
Revises: d4abaf0af059
Create Date: 2026-11-14 11:34:46.472248

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bd33bf39edf6"
down_revision: str | Sequence[str] | None = "d4abaf0af059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE routes ADD COLUMN route_desc TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE routes DROP COLUMN route_desc")
