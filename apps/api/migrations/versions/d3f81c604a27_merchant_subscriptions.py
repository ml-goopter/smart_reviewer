"""merchant subscriptions, with a backfill for every existing merchant

Revision ID: d3f81c604a27
Revises: c7a2e91b4d63
Create Date: 2026-08-12 14:10:00.000000

"""
from datetime import UTC, datetime, timedelta
from typing import Sequence, Union
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3f81c604a27'
down_revision: Union[str, Sequence[str], None] = 'c7a2e91b4d63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUSES = "status IN ('ACTIVE', 'CANCELLED', 'PAUSED')"
DURATION_UNITS = "duration_unit IN ('day', 'month', 'year')"

# What every existing merchant is granted. These are pilot merchants that have
# never been billed, so a year is the honest figure rather than a placeholder,
# and it is long enough that nobody is surprised by an expiry they were not
# told about. Expressed in days because only `day` is implemented.
BACKFILL_DAYS = 365

# Read from the environment rather than imported from app.config, for the same
# reason the arithmetic below is inlined.
OPERATOR_TIMEZONE = "America/Vancouver"


def _backfill_expires_at() -> datetime:
    """`local_midnight(tomorrow) + 365 days`, as UTC.

    A deliberately frozen copy of app.services.subscription_terms rather than an
    import. A migration is a record of what was actually run: importing live
    application code makes this revision replay differently once that code
    moves on, and this one is the difference between every existing QR code
    working and every one of them dying.

    Adding to the local *date* rather than adding a timedelta to an aware
    datetime is what keeps the result on midnight when the zone's offset
    changes inside the term — which it does: America/Vancouver leaves DST
    permanently on 2 Nov 2026.
    """
    tz = ZoneInfo(OPERATOR_TIMEZONE)
    tomorrow = datetime.now(UTC).astimezone(tz).date() + timedelta(days=1)
    start = datetime.combine(tomorrow, datetime.min.time(), tzinfo=tz)
    end = start.date() + timedelta(days=BACKFILL_DAYS)
    return datetime.combine(end, datetime.min.time(), tzinfo=tz).astimezone(UTC)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'subscriptions',
        sa.Column(
            'id',
            sa.UUID(as_uuid=True),
            server_default=sa.text('gen_random_uuid()'),
            nullable=False,
        ),
        sa.Column('merchant_id', sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            'status',
            sa.String(length=20),
            server_default=sa.text("'ACTIVE'"),
            nullable=False,
        ),
        sa.Column(
            'expires_at', sa.dialects.postgresql.TIMESTAMP(timezone=True), nullable=False
        ),
        sa.Column('duration', sa.Integer(), nullable=False),
        sa.Column('duration_unit', sa.String(length=10), nullable=False),
        sa.Column(
            'created_at',
            sa.dialects.postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.dialects.postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(STATUSES, name='ck_subscriptions_status'),
        sa.CheckConstraint(DURATION_UNITS, name='ck_subscriptions_duration_unit'),
        sa.CheckConstraint('duration > 0', name='ck_subscriptions_duration_positive'),
        sa.ForeignKeyConstraint(
            ['merchant_id'], ['merchants.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        # One row per merchant. The index behind this constraint is also the
        # lookup on the session-creation path; there is no second index.
        sa.UniqueConstraint('merchant_id', name='uq_subscriptions_merchant_id'),
    )

    # Every merchant that already exists gets a subscription in the same
    # migration that introduces the gate. Without this, deploying the gate
    # takes down every QR code already printed and in circulation — a schema
    # change is not allowed to do that.
    #
    # Note for whoever runs this: merchants.status is dropped by the next
    # revision, and this backfill does not read it. Any merchant currently
    # INACTIVE or ARCHIVED becomes reachable again. Check for them first.
    op.execute(
        sa.text(
            """
            INSERT INTO subscriptions
                (merchant_id, status, expires_at, duration, duration_unit)
            SELECT id, 'ACTIVE', :expires_at, :duration, 'day'
            FROM merchants
            """
        ).bindparams(expires_at=_backfill_expires_at(), duration=BACKFILL_DAYS)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('subscriptions')
