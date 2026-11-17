"""add route names

Revision ID: 3c2e7a91d4f0
Revises: b6931b6f49dd
Create Date: 2026-11-17 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c2e7a91d4f0"
down_revision: str | Sequence[str] | None = "b6931b6f49dd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE route_names (
            route_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            seen_at TIMESTAMPTZ NOT NULL
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE route_names")
