"""enable postgis

Revision ID: 528efbe95916
Revises:
Create Date: 2026-10-27 15:51:41.457563

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "528efbe95916"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION postgis")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP EXTENSION postgis")
