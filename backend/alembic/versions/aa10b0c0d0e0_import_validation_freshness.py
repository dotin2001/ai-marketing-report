"""Retain source and period identities on import validation results.

Revision ID: aa10b0c0d0e0
Revises: c81d2e7f0a42
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "aa10b0c0d0e0"
down_revision: Union[str, Sequence[str], None] = "c81d2e7f0a42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Historical rows remain nullable and therefore cannot satisfy the new
    # freshness gate. Inferring their identity from mutable report state is unsafe.
    op.add_column("import_validations", sa.Column("source_checksum", sa.LargeBinary(32)))
    op.add_column("import_validations", sa.Column("period_start", sa.Date()))
    op.add_column("import_validations", sa.Column("period_end", sa.Date()))
    op.add_column("import_validations", sa.Column("period_revision", sa.Integer()))
    op.add_column("import_validations", sa.Column("total_records", sa.Integer()))
    op.create_check_constraint(
        "source_checksum_length",
        "import_validations",
        "source_checksum IS NULL OR octet_length(source_checksum) = 32",
    )
    op.create_check_constraint(
        "period_revision_positive",
        "import_validations",
        "period_revision IS NULL OR period_revision > 0",
    )
    op.create_check_constraint(
        "total_records_nonnegative",
        "import_validations",
        "total_records IS NULL OR total_records >= 0",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM import_validations WHERE source_checksum IS NOT NULL) THEN RAISE EXCEPTION 'guarded downgrade refused: new import validations exist'; END IF; END $$;"
        )
    )
    op.drop_constraint("total_records_nonnegative", "import_validations", type_="check")
    op.drop_constraint("period_revision_positive", "import_validations", type_="check")
    op.drop_constraint("source_checksum_length", "import_validations", type_="check")
    op.drop_column("import_validations", "total_records")
    op.drop_column("import_validations", "period_revision")
    op.drop_column("import_validations", "period_end")
    op.drop_column("import_validations", "period_start")
    op.drop_column("import_validations", "source_checksum")
