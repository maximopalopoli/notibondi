"""add schedules

Revision ID: 8a601119415d
Revises: 7def87ba8890
Create Date: 2026-11-11 11:35:53.460501

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a601119415d"
down_revision: str | Sequence[str] | None = "7def87ba8890"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE stop_times ADD COLUMN arrival_time TEXT")
    op.execute("ALTER TABLE trips ADD COLUMN service_id TEXT")
    op.execute("ALTER TABLE trips ADD COLUMN trip_headsign TEXT")
    op.execute("""
        CREATE TABLE calendar_dates (
            service_id TEXT NOT NULL,
            service_date DATE NOT NULL,
            exception_type SMALLINT NOT NULL,
            PRIMARY KEY (service_id, service_date)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE calendar_dates")
    op.execute("ALTER TABLE trips DROP COLUMN trip_headsign")
    op.execute("ALTER TABLE trips DROP COLUMN service_id")
    op.execute("ALTER TABLE stop_times DROP COLUMN arrival_time")
