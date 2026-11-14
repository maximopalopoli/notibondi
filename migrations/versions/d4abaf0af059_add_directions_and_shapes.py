"""add directions and shapes

Revision ID: d4abaf0af059
Revises: f670c200d5b6
Create Date: 2026-11-14 10:40:46.826162

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4abaf0af059"
down_revision: str | Sequence[str] | None = "f670c200d5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE trips ADD COLUMN direction_id SMALLINT")
    op.execute("ALTER TABLE trips ADD COLUMN shape_id TEXT")
    op.execute("ALTER TABLE stop_times ADD COLUMN stop_sequence INTEGER")

    op.execute("""CREATE TABLE shapes (
        shape_id TEXT NOT NULL,
        shape_pt_sequence INTEGER NOT NULL,
        geom geometry(Point, 4326) NOT NULL,
        PRIMARY KEY (shape_id, shape_pt_sequence)
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE shapes")

    op.execute("ALTER TABLE stop_times DROP COLUMN stop_sequence")
    op.execute("ALTER TABLE trips DROP COLUMN shape_id")
    op.execute("ALTER TABLE trips DROP COLUMN direction_id")
