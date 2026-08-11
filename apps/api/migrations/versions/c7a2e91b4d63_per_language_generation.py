"""per-language suggestion generation

Revision ID: c7a2e91b4d63
Revises: b1d4c2f7a3e9
Create Date: 2026-08-10 17:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7a2e91b4d63'
down_revision: Union[str, Sequence[str], None] = 'b1d4c2f7a3e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LANGUAGES = "language IN ('en', 'zh-Hant', 'zh-Hans')"


def upgrade() -> None:
    """Upgrade schema."""
    # Existing rows were all written by an English-only prompt, so the server
    # default backfills them correctly rather than merely plausibly.
    op.add_column(
        'smart_review_suggestions',
        sa.Column(
            'language',
            sa.String(length=20),
            server_default=sa.text("'en'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        'ck_suggestion_language', 'smart_review_suggestions', LANGUAGES
    )

    # generation_number restarts per language, so English batch 1 and Chinese
    # batch 1 both hold a position 1. Without language in the key the second
    # one written would be rejected.
    op.drop_constraint(
        'uq_suggestion_session_generation_position',
        'smart_review_suggestions',
        type_='unique',
    )
    op.create_unique_constraint(
        'uq_suggestion_session_generation_position',
        'smart_review_suggestions',
        ['session_id', 'language', 'generation_number', 'position'],
    )

    op.create_table(
        'smart_review_session_languages',
        sa.Column('session_id', sa.UUID(as_uuid=True), nullable=False),
        sa.Column('language', sa.String(length=20), nullable=False),
        sa.Column(
            'generation_count',
            sa.Integer(),
            server_default=sa.text('0'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['session_id'], ['smart_review_sessions.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('session_id', 'language'),
        sa.CheckConstraint(LANGUAGES, name='ck_session_languages_language'),
        sa.CheckConstraint(
            'generation_count >= 0', name='ck_session_languages_count_non_negative'
        ),
    )

    # Carried across before the column goes, so a session mid-flight when this
    # runs keeps the generations it has already spent instead of being handed a
    # fresh English allowance. Sessions that never generated get no row, which
    # is the same thing a zero would mean.
    op.execute(
        "INSERT INTO smart_review_session_languages "
        "    (session_id, language, generation_count) "
        "SELECT id, 'en', generation_count FROM smart_review_sessions "
        "WHERE generation_count > 0"
    )

    # The per-language table is now the only successful-batch counter; a second
    # one on the session would be a duplicate that nothing keeps in step.
    op.drop_constraint(
        'ck_sessions_counts_non_negative', 'smart_review_sessions', type_='check'
    )
    op.drop_column('smart_review_sessions', 'generation_count')
    op.create_check_constraint(
        'ck_sessions_counts_non_negative',
        'smart_review_sessions',
        'open_count >= 0 AND suggestion_count >= 0 AND generation_attempts >= 0',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        'smart_review_sessions',
        sa.Column(
            'generation_count',
            sa.Integer(),
            server_default=sa.text('0'),
            nullable=False,
        ),
    )
    # Sums every language back into the single counter it came from. A session
    # that generated in more than one language comes back over the old cap,
    # which is the honest result — those batches were generated.
    op.execute(
        "UPDATE smart_review_sessions AS s SET generation_count = totals.total "
        "FROM (SELECT session_id, sum(generation_count) AS total "
        "      FROM smart_review_session_languages GROUP BY session_id) AS totals "
        "WHERE s.id = totals.session_id"
    )
    op.drop_constraint(
        'ck_sessions_counts_non_negative', 'smart_review_sessions', type_='check'
    )
    op.create_check_constraint(
        'ck_sessions_counts_non_negative',
        'smart_review_sessions',
        'open_count >= 0 AND generation_count >= 0 AND suggestion_count >= 0 '
        'AND generation_attempts >= 0',
    )

    op.drop_table('smart_review_session_languages')

    # Suggestions in a second language collide on (session, generation, position)
    # once language leaves the key, so they go before the constraint is narrowed.
    op.execute("DELETE FROM smart_review_suggestions WHERE language <> 'en'")
    op.drop_constraint(
        'uq_suggestion_session_generation_position',
        'smart_review_suggestions',
        type_='unique',
    )
    op.create_unique_constraint(
        'uq_suggestion_session_generation_position',
        'smart_review_suggestions',
        ['session_id', 'generation_number', 'position'],
    )
    op.drop_constraint(
        'ck_suggestion_language', 'smart_review_suggestions', type_='check'
    )
    op.drop_column('smart_review_suggestions', 'language')
