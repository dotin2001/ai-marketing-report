"""Give every metric result an explicit group and null-safe uniqueness.

Revision ID: b12c3d4e5f60
Revises: aa10b0c0d0e0
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b12c3d4e5f60"
down_revision: Union[str, Sequence[str], None] = "aa10b0c0d0e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("metric_results", sa.Column("group_identity", sa.String(64)))
    op.add_column("metric_results", sa.Column("campaign_name", sa.Text()))
    op.execute("ALTER TABLE metric_results DISABLE TRIGGER trg_metric_results_immutable")
    op.execute("UPDATE metric_results SET group_identity = scope")
    op.execute("ALTER TABLE metric_results ENABLE TRIGGER trg_metric_results_immutable")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM metric_results GROUP BY result_set_id, metric_name, scope, coalesce(currency, '') HAVING count(*) > 1) THEN RAISE EXCEPTION 'metric result duplicate groups require repair before upgrade'; END IF; END $$;"
    )
    op.alter_column("metric_results", "group_identity", nullable=False)
    op.drop_constraint("uq_metric_results_metric_scope", "metric_results", type_="unique")
    op.create_index(
        "uq_metric_results_group_currency",
        "metric_results",
        ["result_set_id", "metric_name", "group_identity", sa.text("coalesce(currency, '')")],
        unique=True,
    )
    op.create_check_constraint(
        "group_contract",
        "metric_results",
        "(scope = 'campaign' AND campaign_name IS NOT NULL AND btrim(campaign_name) <> '' AND group_identity <> 'report') OR (scope IN ('report','currency') AND campaign_name IS NULL AND group_identity = scope)",
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM metric_results WHERE scope = 'campaign') THEN RAISE EXCEPTION 'guarded downgrade refused: campaign metrics exist'; END IF; END $$;"
    )
    op.drop_constraint("group_contract", "metric_results", type_="check")
    op.drop_index("uq_metric_results_group_currency", table_name="metric_results")
    op.create_unique_constraint(
        "uq_metric_results_metric_scope",
        "metric_results",
        ["result_set_id", "metric_name", "scope", "currency"],
    )
    op.drop_column("metric_results", "campaign_name")
    op.drop_column("metric_results", "group_identity")
