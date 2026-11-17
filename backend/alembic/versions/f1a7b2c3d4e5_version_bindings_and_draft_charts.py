"""Bind report versions to immutable results and persist draft charts.

Revision ID: f1a7b2c3d4e5
Revises: 24f559f65475
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a7b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "24f559f65475"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "draft_charts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("draft_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("chart_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("x_label", sa.String(length=80), nullable=True),
        sa.Column("y_label", sa.String(length=80), nullable=True),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["draft_id", "report_id", "owner_id"],
            ["report_drafts.id", "report_drafts.report_id", "report_drafts.owner_id"],
            name="fk_draft_charts_draft_aggregate",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draft_charts")),
        sa.UniqueConstraint("draft_id", "ordinal", name="uq_draft_charts_order"),
        sa.UniqueConstraint(
            "id", "draft_id", "report_id", "owner_id", name="uq_draft_charts_aggregate"
        ),
        sa.CheckConstraint("ordinal > 0", name=op.f("ck_draft_charts_ordinal_positive")),
        sa.CheckConstraint(
            "chart_type IN ('bar','line','table')", name=op.f("ck_draft_charts_chart_type_allowed")
        ),
        sa.CheckConstraint("btrim(title) <> ''", name=op.f("ck_draft_charts_title_not_blank")),
        sa.CheckConstraint("btrim(scope) <> ''", name=op.f("ck_draft_charts_scope_not_blank")),
    )
    op.create_table(
        "draft_chart_metric_references",
        sa.Column("chart_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("metric_result_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("draft_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chart_id", "draft_id", "report_id", "owner_id"],
            [
                "draft_charts.id",
                "draft_charts.draft_id",
                "draft_charts.report_id",
                "draft_charts.owner_id",
            ],
            name="fk_draft_chart_metric_references_chart",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["metric_result_id", "report_id", "owner_id"],
            ["metric_results.id", "metric_results.report_id", "metric_results.owner_id"],
            name="fk_draft_chart_metric_references_metric",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "chart_id", "ordinal", name=op.f("pk_draft_chart_metric_references")
        ),
        sa.UniqueConstraint(
            "chart_id", "metric_result_id", name="uq_draft_chart_metric_references_metric"
        ),
        sa.CheckConstraint(
            "ordinal > 0", name=op.f("ck_draft_chart_metric_references_ordinal_positive")
        ),
    )
    op.add_column("report_versions", sa.Column("dataset_id", sa.UUID(), nullable=True))
    op.add_column("report_versions", sa.Column("metric_result_set_id", sa.UUID(), nullable=True))
    op.add_column("report_versions", sa.Column("analysis_result_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_report_versions_dataset",
        "report_versions",
        "canonical_datasets",
        ["dataset_id", "report_id", "owner_id"],
        ["id", "report_id", "owner_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_report_versions_metric_result_set",
        "report_versions",
        "metric_result_sets",
        ["metric_result_set_id", "report_id", "owner_id"],
        ["id", "report_id", "owner_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_report_versions_analysis_result",
        "report_versions",
        "analysis_results",
        ["analysis_result_id", "report_id", "owner_id"],
        ["id", "report_id", "owner_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.execute(
        sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM draft_charts)
               OR EXISTS (SELECT 1 FROM report_versions WHERE snapshot_schema_version >= 2
                OR dataset_id IS NOT NULL OR metric_result_set_id IS NOT NULL
                OR analysis_result_id IS NOT NULL) THEN
                RAISE EXCEPTION 'guarded downgrade refused: draft charts or bound report versions exist';
            END IF;
        END $$;
    """)
    )
    op.drop_constraint("fk_report_versions_analysis_result", "report_versions", type_="foreignkey")
    op.drop_constraint(
        "fk_report_versions_metric_result_set", "report_versions", type_="foreignkey"
    )
    op.drop_constraint("fk_report_versions_dataset", "report_versions", type_="foreignkey")
    op.drop_column("report_versions", "analysis_result_id")
    op.drop_column("report_versions", "metric_result_set_id")
    op.drop_column("report_versions", "dataset_id")
    op.drop_table("draft_chart_metric_references")
    op.drop_table("draft_charts")
