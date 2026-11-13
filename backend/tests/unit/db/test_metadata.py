from __future__ import annotations

from typing import cast

from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.schema import DefaultClause

from app.db.base import NAMING_CONVENTION, Base


def test_metadata_has_deterministic_names() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION
    assert all(NAMING_CONVENTION[key] for key in ("pk", "fk", "uq", "ck", "ix"))


def test_model_uuid_and_timestamp_contract() -> None:
    # Concrete table assertions are extended as each aggregate model is introduced.
    for table in Base.metadata.tables.values():
        if "id" in table.c:
            assert isinstance(table.c.id.type, UUID)
            assert table.c.id.server_default is not None
            default = cast(DefaultClause, table.c.id.server_default)
            assert str(default.arg) == "gen_random_uuid()"
        for column in table.c:
            if column.name.endswith("_at"):
                assert isinstance(column.type, TIMESTAMP)
                assert column.type.timezone is True


def test_jsonb_is_reserved_for_report_version_snapshots() -> None:
    jsonb_columns = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.c
        if column.type.__class__.__name__ == "JSONB"
    }
    assert jsonb_columns <= {("report_versions", "snapshot")}


def test_draft_reference_join_tables_are_declared() -> None:
    assert {
        "draft_item_metric_references",
        "draft_item_claim_references",
    } <= set(Base.metadata.tables)


def test_import_issues_do_not_store_rejected_source_values() -> None:
    issue_columns = set(Base.metadata.tables["import_validation_issues"].c.keys())
    assert not {"value", "raw_value", "source_value", "rejected_value"} & issue_columns
