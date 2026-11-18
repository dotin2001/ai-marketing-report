"""Keep objective and source-review freshness independent of metadata edits.

Revision ID: c81d2e7f0a42
Revises: f1a7b2c3d4e5
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c81d2e7f0a42"
down_revision: Union[str, Sequence[str], None] = "f1a7b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("period_revision", sa.Integer(), nullable=True))
    op.execute("UPDATE reports SET period_revision = 1")
    op.alter_column("reports", "period_revision", nullable=False)
    op.create_check_constraint(
        op.f("ck_reports_period_revision_positive"), "reports", "period_revision > 0"
    )
    op.add_column(
        "idempotency_records",
        sa.Column("result_snapshot", sa.Text(), nullable=True),
    )
    op.add_column("report_drafts", sa.Column("objectives_revision", sa.Integer(), nullable=True))
    op.execute("UPDATE report_drafts SET objectives_revision = revision")
    op.alter_column("report_drafts", "objectives_revision", nullable=False)
    op.create_check_constraint(
        op.f("ck_report_drafts_objectives_revision_valid"),
        "report_drafts",
        "objectives_revision > 0 AND objectives_revision <= revision",
    )
    op.add_column(
        "source_review_confirmations", sa.Column("period_start", sa.Date(), nullable=True)
    )
    op.add_column("source_review_confirmations", sa.Column("period_end", sa.Date(), nullable=True))
    op.add_column(
        "source_review_confirmations", sa.Column("period_revision", sa.Integer(), nullable=True)
    )
    op.execute("""UPDATE source_review_confirmations AS c
                  SET period_start = r.period_start, period_end = r.period_end,
                      period_revision = r.period_revision
                  FROM reports AS r WHERE r.id = c.report_id AND r.owner_id = c.owner_id""")
    op.alter_column("source_review_confirmations", "period_start", nullable=False)
    op.alter_column("source_review_confirmations", "period_end", nullable=False)
    op.alter_column("source_review_confirmations", "period_revision", nullable=False)
    op.drop_constraint(
        "uq_source_review_confirmations_exact_source", "source_review_confirmations", type_="unique"
    )
    op.create_unique_constraint(
        "uq_source_review_confirmations_exact_source",
        "source_review_confirmations",
        ["source_id", "source_checksum", "period_revision"],
    )
    op.create_check_constraint(
        op.f("ck_source_review_confirmations_period_inclusive"),
        "source_review_confirmations",
        "period_end >= period_start",
    )
    op.create_check_constraint(
        op.f("ck_source_review_confirmations_period_revision_positive"),
        "source_review_confirmations",
        "period_revision > 0",
    )


def downgrade() -> None:
    changed_periods = op.get_bind().scalar(
        sa.text("SELECT 1 FROM reports WHERE period_revision <> 1 LIMIT 1")
    )
    if changed_periods is not None:
        raise RuntimeError("cannot safely downgrade changed report periods")
    existing_snapshots = op.get_bind().scalar(
        sa.text("SELECT 1 FROM idempotency_records WHERE result_snapshot IS NOT NULL LIMIT 1")
    )
    if existing_snapshots is not None:
        raise RuntimeError("cannot safely downgrade stored idempotency responses")
    changed_objectives = op.get_bind().scalar(
        sa.text("SELECT 1 FROM report_drafts WHERE objectives_revision <> revision LIMIT 1")
    )
    if changed_objectives is not None:
        raise RuntimeError("cannot safely downgrade distinct objective revisions")
    duplicate = op.get_bind().scalar(
        sa.text("""SELECT 1 FROM source_review_confirmations
        GROUP BY source_id, source_checksum HAVING count(*) > 1 LIMIT 1""")
    )
    if duplicate is not None:
        raise RuntimeError("cannot safely downgrade repeated source review confirmations")
    op.drop_constraint(
        op.f("ck_source_review_confirmations_period_inclusive"),
        "source_review_confirmations",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_source_review_confirmations_period_revision_positive"),
        "source_review_confirmations",
        type_="check",
    )
    op.drop_constraint(
        "uq_source_review_confirmations_exact_source", "source_review_confirmations", type_="unique"
    )
    op.create_unique_constraint(
        "uq_source_review_confirmations_exact_source",
        "source_review_confirmations",
        ["source_id", "source_checksum"],
    )
    op.drop_column("source_review_confirmations", "period_end")
    op.drop_column("source_review_confirmations", "period_start")
    op.drop_column("source_review_confirmations", "period_revision")
    op.drop_constraint(
        op.f("ck_report_drafts_objectives_revision_valid"), "report_drafts", type_="check"
    )
    op.drop_column("report_drafts", "objectives_revision")
    op.drop_column("idempotency_records", "result_snapshot")
    op.drop_constraint(op.f("ck_reports_period_revision_positive"), "reports", type_="check")
    op.drop_column("reports", "period_revision")
