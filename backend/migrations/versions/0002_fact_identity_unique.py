"""unique fact identity

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22 14:02:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'uq_fact_identity',
        'fact',
        ['subject_type', 'subject_id', 'predicate', 'source_id', 'as_of',
         sa.text('md5(value::text)')],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_fact_identity', table_name='fact')
