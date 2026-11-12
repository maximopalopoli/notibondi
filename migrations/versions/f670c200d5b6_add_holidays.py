"""add holidays

Revision ID: f670c200d5b6
Revises: 0129aaefcc16
Create Date: 2026-11-12 09:53:03.659147

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f670c200d5b6"
down_revision: str | Sequence[str] | None = "0129aaefcc16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE holidays (
            holiday_date DATE PRIMARY KEY,
            name TEXT NOT NULL
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE holidays")
