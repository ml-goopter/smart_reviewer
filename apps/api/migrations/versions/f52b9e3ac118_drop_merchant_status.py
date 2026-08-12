"""drop merchants.status — the subscription is the availability gate

Revision ID: f52b9e3ac118
Revises: d3f81c604a27
Create Date: 2026-08-12 14:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f52b9e3ac118'
down_revision: Union[str, Sequence[str], None] = 'd3f81c604a27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUSES = "status IN ('ACTIVE', 'INACTIVE', 'ARCHIVED')"


def upgrade() -> None:
    """Upgrade schema.

    Separate from the revision that creates `subscriptions` so the backfill is
    already committed before the old gate disappears: at no point is a merchant
    ungated by both.

    The CHECK goes with the column automatically; dropping it first would be
    redundant. Nothing reads `status` by the time this runs — both checks in
    app.services.sessions were removed in the change before this one.
    """
    op.drop_column('merchants', 'status')


def downgrade() -> None:
    """Downgrade schema.

    Restores the column and its constraint, but not the values: which merchants
    were INACTIVE or ARCHIVED is not recoverable, so everything comes back
    ACTIVE. The upgrade is effectively one-way, which is why it is worth
    auditing for non-ACTIVE rows before running it.
    """
    op.add_column(
        'merchants',
        sa.Column(
            'status',
            sa.String(length=20),
            server_default=sa.text("'ACTIVE'"),
            nullable=False,
        ),
    )
    op.create_check_constraint('ck_merchants_status', 'merchants', STATUSES)
