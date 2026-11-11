"""add stop times arrival index

Revision ID: 0129aaefcc16
Revises: 8a601119415d
Create Date: 2026-11-11 17:08:27.001963

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0129aaefcc16"
down_revision: str | Sequence[str] | None = "8a601119415d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX stop_times_stop_arrival_idx ON stop_times (stop_id, arrival_time)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX stop_times_stop_arrival_idx")
