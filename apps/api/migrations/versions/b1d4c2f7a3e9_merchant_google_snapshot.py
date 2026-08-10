"""merchant google snapshot and source

Revision ID: b1d4c2f7a3e9
Revises: e588b5708369
Create Date: 2026-08-10 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1d4c2f7a3e9'
down_revision: Union[str, Sequence[str], None] = 'e588b5708369'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('merchants', sa.Column('website', sa.Text(), nullable=True))
    op.add_column('merchants', sa.Column('google_rating', sa.Numeric(2, 1), nullable=True))
    op.add_column('merchants', sa.Column('google_review_count', sa.Integer(), nullable=True))
    op.add_column(
        'merchants',
        sa.Column('google_synced_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # NOT NULL with a server default rather than a backfill: seeding is the only
    # path that existed before the lead crawler, so every pre-existing row is
    # already 'YAML' and the default labels them correctly on its own.
    op.add_column(
        'merchants',
        sa.Column(
            'source',
            sa.String(length=30),
            server_default=sa.text("'YAML'"),
            nullable=False,
        ),
    )
    # Autogenerate does not detect CHECK constraints, so the vocabulary guard is
    # written by hand — same reasoning as the status column it sits beside.
    op.create_check_constraint(
        'ck_merchants_source',
        'merchants',
        "source IN ('YAML', 'GOOGLE_PLACES')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_merchants_source', 'merchants', type_='check')
    op.drop_column('merchants', 'source')
    op.drop_column('merchants', 'google_synced_at')
    op.drop_column('merchants', 'google_review_count')
    op.drop_column('merchants', 'google_rating')
    op.drop_column('merchants', 'website')
