"""add route_stops table

Revision ID: b6931b6f49dd
Revises: bd33bf39edf6
Create Date: 2026-11-14 11:54:32.070354

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6931b6f49dd"
down_revision: str | Sequence[str] | None = "bd33bf39edf6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE route_stops (
            route_id TEXT NOT NULL,
            direction_id SMALLINT NOT NULL,
            stop_sequence INTEGER NOT NULL,
            stop_id TEXT NOT NULL,
            trip_id TEXT NOT NULL,
            PRIMARY KEY (route_id, direction_id, stop_sequence)
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE route_stops")
