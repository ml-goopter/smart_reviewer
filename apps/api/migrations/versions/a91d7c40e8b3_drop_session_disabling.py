"""drop smart_review_sessions.disabled_at — expiry is the only session gate

Revision ID: a91d7c40e8b3
Revises: f52b9e3ac118
Create Date: 2026-08-12 15:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a91d7c40e8b3'
down_revision: Union[str, Sequence[str], None] = 'f52b9e3ac118'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_STATUSES = "status IN ('ACTIVE', 'COMPLETED', 'DISABLED')"
NEW_STATUSES = "status IN ('ACTIVE', 'COMPLETED')"


def upgrade() -> None:
    """Upgrade schema.

    Nothing ever wrote either of these. The check on `disabled_at` could not
    fire in production, and `DISABLED` was a status no code path set — so this
    drops a capability the product only appeared to have.

    Any row that somehow holds DISABLED is moved to COMPLETED rather than
    ACTIVE: it is a session somebody meant to end, and COMPLETED is the
    terminal one. `status` gates nothing either way (R7).
    """
    op.execute(
        sa.text(
            "UPDATE smart_review_sessions SET status = 'COMPLETED' "
            "WHERE status = 'DISABLED'"
        )
    )
    op.drop_constraint('ck_sessions_status', 'smart_review_sessions')
    op.create_check_constraint(
        'ck_sessions_status', 'smart_review_sessions', NEW_STATUSES
    )
    op.drop_column('smart_review_sessions', 'disabled_at')


def downgrade() -> None:
    """Downgrade schema. The column comes back empty — which is what it held."""
    op.add_column(
        'smart_review_sessions',
        sa.Column(
            'disabled_at',
            sa.dialects.postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.drop_constraint('ck_sessions_status', 'smart_review_sessions')
    op.create_check_constraint(
        'ck_sessions_status', 'smart_review_sessions', OLD_STATUSES
    )
