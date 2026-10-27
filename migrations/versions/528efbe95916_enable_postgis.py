"""enable postgis

Revision ID: 528efbe95916
Revises: 
Create Date: 2026-10-27 15:51:41.457563

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '528efbe95916'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION postgis")
    pass


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP EXTENSION postgis")
    pass
