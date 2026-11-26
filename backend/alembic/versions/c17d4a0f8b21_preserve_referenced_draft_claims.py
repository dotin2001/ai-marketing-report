"""Keep removed draft claims for immutable analysis references.

Revision ID: c17d4a0f8b21
Revises: b12c3d4e5f60
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c17d4a0f8b21"
down_revision: Union[str, Sequence[str], None] = "b12c3d4e5f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "draft_claims",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.drop_constraint("uq_draft_claims_order", "draft_claims", type_="unique")
    op.create_index(
        "uq_draft_claims_active_order",
        "draft_claims",
        ["draft_id", "ordinal"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    inactive = connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM draft_claims WHERE NOT is_active)")
    ).scalar()
    if inactive:
        raise RuntimeError("cannot safely discard inactive historical draft claims")
    op.drop_index("uq_draft_claims_active_order", table_name="draft_claims")
    op.create_unique_constraint("uq_draft_claims_order", "draft_claims", ["draft_id", "ordinal"])
    op.drop_column("draft_claims", "is_active")
