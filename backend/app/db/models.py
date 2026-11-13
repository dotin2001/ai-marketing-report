"""Typed reporting-domain persistence models.

The models deliberately contain structural database invariants only. Lifecycle
decisions and calculations remain in domain services introduced by later stages.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

UUID_TYPE = PG_UUID(as_uuid=True)
SHA256_LENGTH = 32


def uuid_column(*, nullable: bool = False) -> Mapped[UUID]:
    return mapped_column(UUID_TYPE, nullable=nullable)


def instant_column(*, nullable: bool = False) -> Mapped[datetime]:
    return mapped_column(TIMESTAMP(timezone=True), nullable=nullable)


class Principal(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "principals"

    identity_namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        UniqueConstraint("identity_namespace", "subject", name="uq_principals_identity"),
        CheckConstraint("btrim(identity_namespace) <> ''", name="identity_namespace_not_blank"),
        CheckConstraint("btrim(subject) <> ''", name="subject_not_blank"),
    )


class Report(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reports"

    owner_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    current_source_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    current_dataset_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    current_metric_result_set_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    current_analysis_result_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)

    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_reports_id_owner"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        CheckConstraint("period_end >= period_start", name="period_inclusive"),
        Index(
            "ix_reports_owner_created_keyset", "owner_id", text("created_at DESC"), text("id DESC")
        ),
    )


class ReportDraft(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "report_drafts"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    current_metric_result_set_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    current_analysis_result_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)

    __table_args__ = (
        ForeignKeyConstraint(
            ["report_id", "owner_id"],
            ["reports.id", "reports.owner_id"],
            name="fk_report_drafts_report_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_report_drafts_aggregate"),
        CheckConstraint("revision > 0", name="revision_positive"),
        Index(
            "uq_report_drafts_one_active",
            "report_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )


class DraftObjective(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "draft_objectives"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    draft_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["draft_id", "report_id", "owner_id"],
            ["report_drafts.id", "report_drafts.report_id", "report_drafts.owner_id"],
            name="fk_draft_objectives_draft_aggregate",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("draft_id", "ordinal", name="uq_draft_objectives_ordinal"),
        UniqueConstraint(
            "id", "draft_id", "report_id", "owner_id", name="uq_draft_objectives_aggregate"
        ),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint("btrim(content) <> ''", name="content_not_blank"),
    )


class DraftNarrativeItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "draft_narrative_items"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    draft_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    section: Mapped[str] = mapped_column(String(32), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    classification: Mapped[str | None] = mapped_column(String(16))

    __table_args__ = (
        ForeignKeyConstraint(
            ["draft_id", "report_id", "owner_id"],
            ["report_drafts.id", "report_drafts.report_id", "report_drafts.owner_id"],
            name="fk_draft_narrative_items_draft_aggregate",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("draft_id", "section", "ordinal", name="uq_draft_narrative_items_order"),
        UniqueConstraint(
            "id", "draft_id", "report_id", "owner_id", name="uq_draft_narrative_items_aggregate"
        ),
        CheckConstraint(
            "section IN ('summary','findings','anomalies','recommendations','data_gaps')",
            name="section_allowed",
        ),
        CheckConstraint(
            "classification IS NULL OR classification IN ('observation','hypothesis','user_claim')",
            name="classification_allowed",
        ),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint("btrim(content) <> ''", name="content_not_blank"),
    )


class DraftLimitation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "draft_limitations"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    draft_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["draft_id", "report_id", "owner_id"],
            ["report_drafts.id", "report_drafts.report_id", "report_drafts.owner_id"],
            name="fk_draft_limitations_draft_aggregate",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("draft_id", "ordinal", name="uq_draft_limitations_order"),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint("btrim(content) <> ''", name="content_not_blank"),
    )


class DraftClaim(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "draft_claims"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    draft_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    classification: Mapped[str] = mapped_column(String(16), nullable=False, default="user_claim")
    source_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)

    __table_args__ = (
        ForeignKeyConstraint(
            ["draft_id", "report_id", "owner_id"],
            ["report_drafts.id", "report_drafts.report_id", "report_drafts.owner_id"],
            name="fk_draft_claims_draft_aggregate",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("draft_id", "ordinal", name="uq_draft_claims_order"),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_draft_claims_aggregate"),
        CheckConstraint("classification = 'user_claim'", name="classification_user_claim"),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint("btrim(content) <> ''", name="content_not_blank"),
    )


class DraftItemMetricReference(Base):
    __tablename__ = "draft_item_metric_references"

    item_id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True)
    metric_result_id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    draft_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["item_id", "draft_id", "report_id", "owner_id"],
            [
                "draft_narrative_items.id",
                "draft_narrative_items.draft_id",
                "draft_narrative_items.report_id",
                "draft_narrative_items.owner_id",
            ],
            name="fk_draft_item_metric_references_item",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["metric_result_id", "report_id", "owner_id"],
            ["metric_results.id", "metric_results.report_id", "metric_results.owner_id"],
            name="fk_draft_item_metric_references_metric",
            ondelete="RESTRICT",
        ),
    )


class DraftItemClaimReference(Base):
    __tablename__ = "draft_item_claim_references"

    item_id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    draft_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["item_id", "draft_id", "report_id", "owner_id"],
            [
                "draft_narrative_items.id",
                "draft_narrative_items.draft_id",
                "draft_narrative_items.report_id",
                "draft_narrative_items.owner_id",
            ],
            name="fk_draft_item_claim_references_item",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["claim_id", "report_id", "owner_id"],
            ["draft_claims.id", "draft_claims.report_id", "draft_claims.owner_id"],
            name="fk_draft_item_claim_references_claim",
            ondelete="RESTRICT",
        ),
    )


class FileAsset(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "file_assets"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[bytes] = mapped_column(LargeBinary(SHA256_LENGTH), nullable=False)
    version_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    export_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)

    __table_args__ = (
        ForeignKeyConstraint(
            ["report_id", "owner_id"],
            ["reports.id", "reports.owner_id"],
            name="fk_file_assets_report_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "environment", "bucket", "object_key", name="uq_file_assets_object_identity"
        ),
        UniqueConstraint(
            "id", "report_id", "owner_id", "purpose", name="uq_file_assets_purpose_aggregate"
        ),
        UniqueConstraint(
            "id",
            "export_id",
            "version_id",
            "report_id",
            "owner_id",
            "purpose",
            name="uq_file_assets_export_binding",
        ),
        CheckConstraint("purpose IN ('source_csv','generated_pdf')", name="purpose_allowed"),
        CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        CheckConstraint("octet_length(checksum_sha256) = 32", name="checksum_sha256_length"),
        CheckConstraint(
            "btrim(environment) <> '' AND btrim(bucket) <> '' AND btrim(object_key) <> ''",
            name="object_identity_not_blank",
        ),
        CheckConstraint(
            "(purpose = 'source_csv' AND version_id IS NULL AND export_id IS NULL) OR "
            "(purpose = 'generated_pdf' AND version_id IS NOT NULL AND export_id IS NOT NULL "
            "AND content_type = 'application/pdf' AND byte_size > 0)",
            name="purpose_binding_shape",
        ),
    )


class ReportSource(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "report_sources"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    source_type: Mapped[str] = mapped_column(String(8), nullable=False)
    checksum_sha256: Mapped[bytes] = mapped_column(LargeBinary(SHA256_LENGTH), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    encoding: Mapped[str | None] = mapped_column(String(64))
    inline_text: Mapped[str | None] = mapped_column(Text)
    asset_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    asset_purpose: Mapped[str | None] = mapped_column(String(32))
    original_filename: Mapped[str | None] = mapped_column(Text)
    display_filename: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        ForeignKeyConstraint(
            ["report_id", "owner_id"],
            ["reports.id", "reports.owner_id"],
            name="fk_report_sources_report_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["asset_id", "report_id", "owner_id", "asset_purpose"],
            [
                "file_assets.id",
                "file_assets.report_id",
                "file_assets.owner_id",
                "file_assets.purpose",
            ],
            name="fk_report_sources_source_asset",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_report_sources_aggregate"),
        UniqueConstraint(
            "id",
            "report_id",
            "owner_id",
            "source_type",
            name="uq_report_sources_typed_aggregate",
        ),
        CheckConstraint("source_type IN ('text','csv')", name="source_type_allowed"),
        CheckConstraint("byte_size >= 0", name="byte_size_nonnegative"),
        CheckConstraint("octet_length(checksum_sha256) = 32", name="checksum_sha256_length"),
        CheckConstraint(
            "(source_type = 'text' AND inline_text IS NOT NULL AND asset_id IS NULL AND asset_purpose IS NULL AND original_filename IS NULL AND display_filename IS NULL) OR "
            "(source_type = 'csv' AND inline_text IS NULL AND asset_id IS NOT NULL AND asset_purpose = 'source_csv' AND original_filename IS NOT NULL AND display_filename IS NOT NULL)",
            name="representation_exclusive",
        ),
        Index(
            "ix_report_sources_owner_report_checksum", "owner_id", "report_id", "checksum_sha256"
        ),
    )


class ImportConfiguration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "import_configurations"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    source_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    source_type: Mapped[str] = mapped_column(String(8), nullable=False, default="csv")
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "report_id", "owner_id", "source_type"],
            [
                "report_sources.id",
                "report_sources.report_id",
                "report_sources.owner_id",
                "report_sources.source_type",
            ],
            name="fk_import_configurations_source_aggregate",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("source_id", name="uq_import_configurations_source"),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_import_configurations_aggregate"),
        CheckConstraint("source_type = 'csv'", name="source_type_csv"),
        CheckConstraint("current_revision > 0", name="current_revision_positive"),
        Index("ix_import_configurations_current", "owner_id", "report_id", "current_revision"),
    )


class ImportConfigurationRevision(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "import_configuration_revisions"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    configuration_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    normalization_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    date_format: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        ForeignKeyConstraint(
            ["configuration_id", "report_id", "owner_id"],
            [
                "import_configurations.id",
                "import_configurations.report_id",
                "import_configurations.owner_id",
            ],
            name="fk_import_configuration_revisions_configuration",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "configuration_id", "revision", name="uq_import_configuration_revisions_number"
        ),
        UniqueConstraint(
            "configuration_id",
            "revision",
            "report_id",
            "owner_id",
            name="uq_import_configuration_revisions_owner_aggregate",
        ),
        UniqueConstraint(
            "id",
            "configuration_id",
            "revision",
            "report_id",
            "owner_id",
            name="uq_import_configuration_revisions_aggregate",
        ),
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint("btrim(normalization_policy_version) <> ''", name="norm_version_not_blank"),
    )


class ImportColumnMapping(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "import_column_mappings"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    configuration_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_column_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_field: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["configuration_id", "revision", "report_id", "owner_id"],
            [
                "import_configuration_revisions.configuration_id",
                "import_configuration_revisions.revision",
                "import_configuration_revisions.report_id",
                "import_configuration_revisions.owner_id",
            ],
            name="fk_import_column_mappings_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "configuration_id",
            "revision",
            "source_column_ordinal",
            name="uq_import_column_mappings_source_ordinal",
        ),
        UniqueConstraint(
            "configuration_id",
            "revision",
            "canonical_field",
            name="uq_import_column_mappings_canonical_field",
        ),
        CheckConstraint("source_column_ordinal >= 0", name="source_column_ordinal_nonnegative"),
        CheckConstraint(
            "canonical_field IN ('date','campaign_name','currency','impressions','clicks','spend','leads')",
            name="canonical_field_allowed",
        ),
    )


class ImportValidation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "import_validations"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    configuration_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_preview_identity: Mapped[bytes | None] = mapped_column(LargeBinary(SHA256_LENGTH))

    __table_args__ = (
        ForeignKeyConstraint(
            ["configuration_id", "revision", "report_id", "owner_id"],
            [
                "import_configuration_revisions.configuration_id",
                "import_configuration_revisions.revision",
                "import_configuration_revisions.report_id",
                "import_configuration_revisions.owner_id",
            ],
            name="fk_import_validations_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "configuration_id",
            "revision",
            "report_id",
            "owner_id",
            name="uq_import_validations_aggregate",
        ),
        UniqueConstraint(
            "id", "report_id", "owner_id", name="uq_import_validations_owner_aggregate"
        ),
        CheckConstraint("error_count >= 0 AND warning_count >= 0", name="issue_counts_nonnegative"),
    )


class ImportValidationIssue(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "import_validation_issues"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    validation_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    canonical_field: Mapped[str | None] = mapped_column(String(32))
    source_column_ordinal: Mapped[int | None] = mapped_column(Integer)
    source_record_index: Mapped[int | None] = mapped_column(Integer)
    related_record_index: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        ForeignKeyConstraint(
            ["validation_id", "report_id", "owner_id"],
            [
                "import_validations.id",
                "import_validations.report_id",
                "import_validations.owner_id",
            ],
            name="fk_import_validation_issues_validation",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("validation_id", "ordinal", name="uq_import_validation_issues_order"),
        UniqueConstraint(
            "id",
            "validation_id",
            "report_id",
            "owner_id",
            name="uq_import_validation_issues_aggregate",
        ),
        UniqueConstraint(
            "id",
            "report_id",
            "owner_id",
            name="uq_import_validation_issues_owner_aggregate",
        ),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint("severity IN ('error','warning')", name="severity_allowed"),
        CheckConstraint(
            "source_column_ordinal IS NULL OR source_column_ordinal >= 0",
            name="source_column_ordinal_nonnegative",
        ),
        CheckConstraint(
            "source_record_index IS NULL OR source_record_index > 0",
            name="source_record_index_positive",
        ),
        CheckConstraint(
            "related_record_index IS NULL OR related_record_index > 0",
            name="related_record_index_positive",
        ),
        CheckConstraint("btrim(code) <> '' AND btrim(message) <> ''", name="safe_fields_not_blank"),
    )


class ConfirmedImport(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "confirmed_imports"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    validation_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    configuration_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed_by: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    canonical_data_identity: Mapped[bytes] = mapped_column(
        LargeBinary(SHA256_LENGTH), nullable=False
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["validation_id", "configuration_id", "revision", "report_id", "owner_id"],
            [
                "import_validations.id",
                "import_validations.configuration_id",
                "import_validations.revision",
                "import_validations.report_id",
                "import_validations.owner_id",
            ],
            name="fk_confirmed_imports_validation_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["confirmed_by"],
            ["principals.id"],
            name="fk_confirmed_imports_principal",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("validation_id", name="uq_confirmed_imports_validation"),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_confirmed_imports_aggregate"),
        UniqueConstraint("canonical_data_identity", name="uq_confirmed_imports_canonical_identity"),
        CheckConstraint("revision > 0 AND row_count > 0", name="revision_and_rows_positive"),
        CheckConstraint("period_end >= period_start", name="period_inclusive"),
    )


class ConfirmedImportWarningAcknowledgement(Base):
    __tablename__ = "confirmed_import_warning_acknowledgements"

    confirmation_id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True)
    issue_id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["confirmation_id", "report_id", "owner_id"],
            ["confirmed_imports.id", "confirmed_imports.report_id", "confirmed_imports.owner_id"],
            name="fk_warning_acknowledgements_confirmation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["issue_id", "report_id", "owner_id"],
            [
                "import_validation_issues.id",
                "import_validation_issues.report_id",
                "import_validation_issues.owner_id",
            ],
            name="fk_warning_acknowledgements_issue",
            ondelete="RESTRICT",
        ),
    )


class SourceReviewConfirmation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "source_review_confirmations"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    source_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    source_checksum: Mapped[bytes] = mapped_column(LargeBinary(SHA256_LENGTH), nullable=False)
    confirmed_by: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "report_id", "owner_id"],
            ["report_sources.id", "report_sources.report_id", "report_sources.owner_id"],
            name="fk_source_review_confirmations_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["confirmed_by"],
            ["principals.id"],
            name="fk_source_review_confirmations_principal",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "source_id", "source_checksum", name="uq_source_review_confirmations_exact_source"
        ),
    )


class CanonicalDataset(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "canonical_datasets"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    source_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    confirmation_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    canonical_data_identity: Mapped[bytes] = mapped_column(
        LargeBinary(SHA256_LENGTH), nullable=False
    )
    normalization_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "report_id", "owner_id"],
            ["report_sources.id", "report_sources.report_id", "report_sources.owner_id"],
            name="fk_canonical_datasets_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["confirmation_id", "report_id", "owner_id"],
            ["confirmed_imports.id", "confirmed_imports.report_id", "confirmed_imports.owner_id"],
            name="fk_canonical_datasets_confirmation",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("confirmation_id", name="uq_canonical_datasets_confirmation"),
        UniqueConstraint("canonical_data_identity", name="uq_canonical_datasets_identity"),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_canonical_datasets_aggregate"),
        CheckConstraint("row_count > 0", name="row_count_positive"),
        CheckConstraint("period_end >= period_start", name="period_inclusive"),
    )


class DatasetCurrency(Base):
    __tablename__ = "dataset_currencies"

    dataset_id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "report_id", "owner_id"],
            [
                "canonical_datasets.id",
                "canonical_datasets.report_id",
                "canonical_datasets.owner_id",
            ],
            name="fk_dataset_currencies_dataset",
            ondelete="RESTRICT",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_shape"),
    )


class CanonicalRow(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "canonical_rows"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    dataset_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    source_record_index: Mapped[int] = mapped_column(Integer, nullable=False)
    row_date: Mapped[date] = mapped_column(Date, nullable=False)
    campaign_name: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    impressions: Mapped[int | None] = mapped_column(BigInteger)
    clicks: Mapped[int | None] = mapped_column(BigInteger)
    spend: Mapped[Decimal | None] = mapped_column()
    leads: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "report_id", "owner_id"],
            [
                "canonical_datasets.id",
                "canonical_datasets.report_id",
                "canonical_datasets.owner_id",
            ],
            name="fk_canonical_rows_dataset",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "currency"],
            ["dataset_currencies.dataset_id", "dataset_currencies.currency"],
            name="fk_canonical_rows_dataset_currency",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "dataset_id", "source_record_index", name="uq_canonical_rows_source_record"
        ),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_canonical_rows_aggregate"),
        CheckConstraint("source_record_index > 0", name="source_record_index_positive"),
        CheckConstraint("btrim(campaign_name) <> ''", name="campaign_name_not_blank"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_shape"),
        CheckConstraint("impressions IS NULL OR impressions >= 0", name="impressions_nonnegative"),
        CheckConstraint("clicks IS NULL OR clicks >= 0", name="clicks_nonnegative"),
        CheckConstraint("leads IS NULL OR leads >= 0", name="leads_nonnegative"),
        CheckConstraint(
            "spend IS NULL OR (spend >= 0 AND spend NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric))",
            name="spend_nonnegative_finite",
        ),
        CheckConstraint(
            "num_nonnulls(impressions, clicks, spend, leads) > 0", name="at_least_one_measure"
        ),
        Index(
            "ix_canonical_rows_owner_report_dataset_keyset",
            "owner_id",
            "report_id",
            "dataset_id",
            "source_record_index",
            "id",
        ),
    )


class MetricResultSet(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "metric_result_sets"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    dataset_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    identity: Mapped[bytes] = mapped_column(LargeBinary(SHA256_LENGTH), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    calculated_at: Mapped[datetime] = instant_column()

    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "report_id", "owner_id"],
            [
                "canonical_datasets.id",
                "canonical_datasets.report_id",
                "canonical_datasets.owner_id",
            ],
            name="fk_metric_result_sets_dataset",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("identity", name="uq_metric_result_sets_identity"),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_metric_result_sets_aggregate"),
    )


class MetricResult(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "metric_results"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    result_set_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(16), nullable=False)
    availability: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))
    value: Mapped[Decimal | None] = mapped_column()
    unit: Mapped[str | None] = mapped_column(String(64))
    unavailable_reason: Mapped[str | None] = mapped_column(String(32))
    supporting_field: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (
        ForeignKeyConstraint(
            ["result_set_id", "report_id", "owner_id"],
            [
                "metric_result_sets.id",
                "metric_result_sets.report_id",
                "metric_result_sets.owner_id",
            ],
            name="fk_metric_results_result_set",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "result_set_id",
            "metric_name",
            "scope",
            "currency",
            name="uq_metric_results_metric_scope",
        ),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_metric_results_aggregate"),
        CheckConstraint("metric_name IN ('ctr','cpc','cpm','cpl')", name="metric_name_allowed"),
        CheckConstraint("availability IN ('available','unavailable')", name="availability_allowed"),
        CheckConstraint("period_end >= period_start", name="period_inclusive"),
        CheckConstraint("currency IS NULL OR currency ~ '^[A-Z]{3}$'", name="currency_shape"),
        CheckConstraint(
            "value IS NULL OR value NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="value_finite",
        ),
        CheckConstraint(
            "unavailable_reason IS NULL OR unavailable_reason IN ('missing_input','zero_denominator','invalid_input','incompatible_currency','incomparable_period')",
            name="unavailable_reason_allowed",
        ),
        CheckConstraint(
            "(availability = 'available' AND value IS NOT NULL AND unit IS NOT NULL AND unavailable_reason IS NULL AND supporting_field IS NULL) OR (availability = 'unavailable' AND value IS NULL AND unit IS NULL AND unavailable_reason IS NOT NULL)",
            name="availability_variant",
        ),
        CheckConstraint(
            "NOT (scope = 'report' AND metric_name IN ('cpc','cpm','cpl') AND currency IS NULL AND availability = 'available')",
            name="no_combined_monetary_result",
        ),
    )


class MetricResultInput(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "metric_result_inputs"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    metric_result_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    input_name: Mapped[str] = mapped_column(String(32), nullable=False)
    exact_total: Mapped[Decimal] = mapped_column(nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["metric_result_id", "report_id", "owner_id"],
            ["metric_results.id", "metric_results.report_id", "metric_results.owner_id"],
            name="fk_metric_result_inputs_result",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("metric_result_id", "ordinal", name="uq_metric_result_inputs_order"),
        UniqueConstraint("metric_result_id", "input_name", name="uq_metric_result_inputs_name"),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint(
            "exact_total NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
            name="exact_total_finite",
        ),
    )


class MetricResultCurrency(Base):
    __tablename__ = "metric_result_currencies"

    metric_result_id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["metric_result_id", "report_id", "owner_id"],
            ["metric_results.id", "metric_results.report_id", "metric_results.owner_id"],
            name="fk_metric_result_currencies_result",
            ondelete="RESTRICT",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_shape"),
    )


class AnalysisJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "analysis_jobs"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    semantic_input_identity: Mapped[bytes] = mapped_column(
        LargeBinary(SHA256_LENGTH), nullable=False
    )
    dataset_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    metric_result_set_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    draft_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    objectives_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_result_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(String(500))
    failure_retryable: Mapped[bool | None] = mapped_column(Boolean)

    __table_args__ = (
        ForeignKeyConstraint(
            ["report_id", "owner_id"],
            ["reports.id", "reports.owner_id"],
            name="fk_analysis_jobs_report_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "report_id", "owner_id"],
            [
                "canonical_datasets.id",
                "canonical_datasets.report_id",
                "canonical_datasets.owner_id",
            ],
            name="fk_analysis_jobs_dataset",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["metric_result_set_id", "report_id", "owner_id"],
            [
                "metric_result_sets.id",
                "metric_result_sets.report_id",
                "metric_result_sets.owner_id",
            ],
            name="fk_analysis_jobs_metric_set",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["draft_id", "report_id", "owner_id"],
            ["report_drafts.id", "report_drafts.report_id", "report_drafts.owner_id"],
            name="fk_analysis_jobs_draft",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "report_id", "semantic_input_identity", name="uq_analysis_jobs_semantic_input"
        ),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_analysis_jobs_aggregate"),
        CheckConstraint("state IN ('queued','running','succeeded','failed')", name="state_allowed"),
        CheckConstraint(
            "attempt_count > 0 AND draft_revision > 0 AND objectives_revision > 0",
            name="positive_counters",
        ),
        CheckConstraint(
            "(state = 'failed' AND failure_code IS NOT NULL AND failure_message IS NOT NULL AND failure_retryable IS NOT NULL) OR (state <> 'failed' AND failure_code IS NULL AND failure_message IS NULL AND failure_retryable IS NULL)",
            name="failure_shape",
        ),
        Index(
            "ix_analysis_jobs_owner_report_created_keyset",
            "owner_id",
            "report_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
    )


class AnalysisJobAttempt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "analysis_job_attempts"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    job_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    attempt_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    queued_at: Mapped[datetime] = instant_column()
    started_at: Mapped[datetime | None] = instant_column(nullable=True)
    finished_at: Mapped[datetime | None] = instant_column(nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(String(500))
    failure_retryable: Mapped[bool | None] = mapped_column(Boolean)

    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "report_id", "owner_id"],
            ["analysis_jobs.id", "analysis_jobs.report_id", "analysis_jobs.owner_id"],
            name="fk_analysis_job_attempts_job",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("job_id", "attempt_ordinal", name="uq_analysis_job_attempts_ordinal"),
        CheckConstraint("attempt_ordinal > 0", name="attempt_ordinal_positive"),
        CheckConstraint("state IN ('queued','running','succeeded','failed')", name="state_allowed"),
        CheckConstraint(
            "(state = 'queued' AND started_at IS NULL AND finished_at IS NULL) OR (state = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR (state IN ('succeeded','failed') AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="timestamps_match_state",
        ),
        CheckConstraint(
            "(state = 'failed' AND failure_code IS NOT NULL AND failure_message IS NOT NULL AND failure_retryable IS NOT NULL) OR (state <> 'failed' AND failure_code IS NULL AND failure_message IS NULL AND failure_retryable IS NULL)",
            name="failure_shape",
        ),
    )


class AnalysisResult(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "analysis_results"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    job_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    semantic_input_identity: Mapped[bytes] = mapped_column(
        LargeBinary(SHA256_LENGTH), nullable=False
    )
    model_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    request_provenance: Mapped[str] = mapped_column(String(500), nullable=False)
    numeric_source_identity: Mapped[bytes] = mapped_column(
        LargeBinary(SHA256_LENGTH), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "report_id", "owner_id"],
            ["analysis_jobs.id", "analysis_jobs.report_id", "analysis_jobs.owner_id"],
            name="fk_analysis_results_job",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("job_id", name="uq_analysis_results_job"),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_analysis_results_aggregate"),
        UniqueConstraint(
            "id",
            "job_id",
            "report_id",
            "owner_id",
            name="uq_analysis_results_job_aggregate",
        ),
        CheckConstraint(
            "btrim(model_identifier) <> '' AND btrim(prompt_version) <> ''",
            name="provenance_not_blank",
        ),
    )


class AnalysisResultItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "analysis_result_items"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    result_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    section: Mapped[str] = mapped_column(String(32), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    classification: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["result_id", "report_id", "owner_id"],
            ["analysis_results.id", "analysis_results.report_id", "analysis_results.owner_id"],
            name="fk_analysis_result_items_result",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("result_id", "section", "ordinal", name="uq_analysis_result_items_order"),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_analysis_result_items_aggregate"),
        CheckConstraint(
            "section IN ('summary','findings','anomalies','recommendations','data_gaps')",
            name="section_allowed",
        ),
        CheckConstraint(
            "classification IN ('observation','hypothesis','user_claim')",
            name="classification_allowed",
        ),
        CheckConstraint("ordinal > 0", name="ordinal_positive"),
        CheckConstraint("btrim(content) <> ''", name="content_not_blank"),
    )


class AnalysisItemMetricReference(Base):
    __tablename__ = "analysis_item_metric_references"

    item_id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True)
    metric_result_id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["item_id", "report_id", "owner_id"],
            [
                "analysis_result_items.id",
                "analysis_result_items.report_id",
                "analysis_result_items.owner_id",
            ],
            name="fk_analysis_item_metric_references_item",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["metric_result_id", "report_id", "owner_id"],
            ["metric_results.id", "metric_results.report_id", "metric_results.owner_id"],
            name="fk_analysis_item_metric_references_metric",
            ondelete="RESTRICT",
        ),
    )


class AnalysisItemClaimReference(Base):
    __tablename__ = "analysis_item_claim_references"

    item_id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True)
    claim_id: Mapped[UUID] = mapped_column(UUID_TYPE, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["item_id", "report_id", "owner_id"],
            [
                "analysis_result_items.id",
                "analysis_result_items.report_id",
                "analysis_result_items.owner_id",
            ],
            name="fk_analysis_item_claim_references_item",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["claim_id", "report_id", "owner_id"],
            ["draft_claims.id", "draft_claims.report_id", "draft_claims.owner_id"],
            name="fk_analysis_item_claim_references_claim",
            ondelete="RESTRICT",
        ),
    )


class IdempotencyRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "idempotency_records"

    principal_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    key_digest: Mapped[bytes] = mapped_column(LargeBinary(SHA256_LENGTH), nullable=False)
    command_fingerprint: Mapped[bytes] = mapped_column(LargeBinary(SHA256_LENGTH), nullable=False)
    result_type: Mapped[str | None] = mapped_column(String(64))
    result_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    success_status: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint(
            "principal_id",
            "operation",
            "scope_kind",
            "scope_id",
            "key_digest",
            name="uq_idempotency_records_scope_key",
        ),
        CheckConstraint(
            "octet_length(key_digest) = 32 AND octet_length(command_fingerprint) = 32",
            name="digests_sha256",
        ),
        CheckConstraint(
            "(result_type IS NULL AND result_id IS NULL AND success_status IS NULL) OR (result_type IS NOT NULL AND result_id IS NOT NULL AND success_status BETWEEN 200 AND 299)",
            name="result_finalization_shape",
        ),
        Index(
            "ix_idempotency_records_scope", "principal_id", "operation", "scope_kind", "scope_id"
        ),
    )


class ReportVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "report_versions"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_draft_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    source_draft_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    snapshot_identity: Mapped[bytes] = mapped_column(LargeBinary(SHA256_LENGTH), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["report_id", "owner_id"],
            ["reports.id", "reports.owner_id"],
            name="fk_report_versions_report_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_draft_id", "report_id", "owner_id"],
            ["report_drafts.id", "report_drafts.report_id", "report_drafts.owner_id"],
            name="fk_report_versions_draft",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("report_id", "version_number", name="uq_report_versions_number"),
        UniqueConstraint(
            "report_id", "snapshot_identity", name="uq_report_versions_snapshot_identity"
        ),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_report_versions_aggregate"),
        CheckConstraint(
            "version_number > 0 AND source_draft_revision > 0 AND snapshot_schema_version > 0",
            name="positive_versions",
        ),
        Index(
            "ix_report_versions_owner_report_number_keyset",
            "owner_id",
            "report_id",
            text("version_number DESC"),
            text("id DESC"),
        ),
    )


class PdfExport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "pdf_exports"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    version_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    snapshot_identity: Mapped[bytes] = mapped_column(LargeBinary(SHA256_LENGTH), nullable=False)
    template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_identity: Mapped[bytes] = mapped_column(LargeBinary(SHA256_LENGTH), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    generated_asset_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    generated_asset_purpose: Mapped[str | None] = mapped_column(String(32))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(String(500))
    failure_retryable: Mapped[bool | None] = mapped_column(Boolean)

    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "report_id", "owner_id"],
            ["report_versions.id", "report_versions.report_id", "report_versions.owner_id"],
            name="fk_pdf_exports_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "generated_asset_id",
                "id",
                "version_id",
                "report_id",
                "owner_id",
                "generated_asset_purpose",
            ],
            [
                "file_assets.id",
                "file_assets.export_id",
                "file_assets.version_id",
                "file_assets.report_id",
                "file_assets.owner_id",
                "file_assets.purpose",
            ],
            name="fk_pdf_exports_generated_asset",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "version_id",
            "snapshot_identity",
            "template_version",
            name="uq_pdf_exports_logical_input",
        ),
        UniqueConstraint("id", "report_id", "owner_id", name="uq_pdf_exports_aggregate"),
        UniqueConstraint(
            "id", "version_id", "report_id", "owner_id", name="uq_pdf_exports_version_aggregate"
        ),
        CheckConstraint("state IN ('queued','running','succeeded','failed')", name="state_allowed"),
        CheckConstraint("attempt_count > 0", name="attempt_count_positive"),
        CheckConstraint(
            "(state = 'succeeded' AND generated_asset_id IS NOT NULL AND generated_asset_purpose = 'generated_pdf' AND failure_code IS NULL AND failure_message IS NULL AND failure_retryable IS NULL) OR (state = 'failed' AND generated_asset_id IS NULL AND generated_asset_purpose IS NULL AND failure_code IS NOT NULL AND failure_message IS NOT NULL AND failure_retryable IS NOT NULL) OR (state IN ('queued','running') AND generated_asset_id IS NULL AND generated_asset_purpose IS NULL AND failure_code IS NULL AND failure_message IS NULL AND failure_retryable IS NULL)",
            name="state_result_shape",
        ),
        Index(
            "ix_pdf_exports_owner_report_version_created_keyset",
            "owner_id",
            "report_id",
            "version_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
    )


class PdfExportAttempt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "pdf_export_attempts"

    owner_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    report_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    export_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
    attempt_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    queued_at: Mapped[datetime] = instant_column()
    started_at: Mapped[datetime | None] = instant_column(nullable=True)
    finished_at: Mapped[datetime | None] = instant_column(nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(String(500))
    failure_retryable: Mapped[bool | None] = mapped_column(Boolean)

    __table_args__ = (
        ForeignKeyConstraint(
            ["export_id", "report_id", "owner_id"],
            ["pdf_exports.id", "pdf_exports.report_id", "pdf_exports.owner_id"],
            name="fk_pdf_export_attempts_export",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("export_id", "attempt_ordinal", name="uq_pdf_export_attempts_ordinal"),
        CheckConstraint("attempt_ordinal > 0", name="attempt_ordinal_positive"),
        CheckConstraint("state IN ('queued','running','succeeded','failed')", name="state_allowed"),
        CheckConstraint(
            "(state = 'queued' AND started_at IS NULL AND finished_at IS NULL) OR (state = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR (state IN ('succeeded','failed') AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="timestamps_match_state",
        ),
        CheckConstraint(
            "(state = 'failed' AND failure_code IS NOT NULL AND failure_message IS NOT NULL AND failure_retryable IS NOT NULL) OR (state <> 'failed' AND failure_code IS NULL AND failure_message IS NULL AND failure_retryable IS NULL)",
            name="failure_shape",
        ),
    )


# Deferrable current pointers are declared after all target tables exist.
report_table = cast(Table, Report.__table__)
report_table.append_constraint(
    ForeignKeyConstraint(
        ["current_source_id", "id", "owner_id"],
        ["report_sources.id", "report_sources.report_id", "report_sources.owner_id"],
        name="fk_reports_current_source",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
        ondelete="RESTRICT",
    )
)

analysis_job_table = cast(Table, AnalysisJob.__table__)
analysis_job_table.append_constraint(
    ForeignKeyConstraint(
        ["current_result_id", "id", "report_id", "owner_id"],
        [
            "analysis_results.id",
            "analysis_results.job_id",
            "analysis_results.report_id",
            "analysis_results.owner_id",
        ],
        name="fk_analysis_jobs_current_result",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
        ondelete="RESTRICT",
    )
)

file_asset_table = cast(Table, FileAsset.__table__)
file_asset_table.append_constraint(
    ForeignKeyConstraint(
        ["version_id", "report_id", "owner_id"],
        ["report_versions.id", "report_versions.report_id", "report_versions.owner_id"],
        name="fk_file_assets_version",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
        ondelete="RESTRICT",
    )
)
file_asset_table.append_constraint(
    ForeignKeyConstraint(
        ["export_id", "version_id", "report_id", "owner_id"],
        [
            "pdf_exports.id",
            "pdf_exports.version_id",
            "pdf_exports.report_id",
            "pdf_exports.owner_id",
        ],
        name="fk_file_assets_export",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
        ondelete="RESTRICT",
    )
)
report_table.append_constraint(
    ForeignKeyConstraint(
        ["current_dataset_id", "id", "owner_id"],
        ["canonical_datasets.id", "canonical_datasets.report_id", "canonical_datasets.owner_id"],
        name="fk_reports_current_dataset",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
        ondelete="RESTRICT",
    )
)
report_table.append_constraint(
    ForeignKeyConstraint(
        ["current_metric_result_set_id", "id", "owner_id"],
        ["metric_result_sets.id", "metric_result_sets.report_id", "metric_result_sets.owner_id"],
        name="fk_reports_current_metric_result_set",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
        ondelete="RESTRICT",
    )
)
report_table.append_constraint(
    ForeignKeyConstraint(
        ["current_analysis_result_id", "id", "owner_id"],
        ["analysis_results.id", "analysis_results.report_id", "analysis_results.owner_id"],
        name="fk_reports_current_analysis_result",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
        ondelete="RESTRICT",
    )
)


IMMUTABLE_TABLES = (
    "file_assets",
    "report_sources",
    "import_configuration_revisions",
    "import_column_mappings",
    "confirmed_imports",
    "confirmed_import_warning_acknowledgements",
    "source_review_confirmations",
    "canonical_datasets",
    "dataset_currencies",
    "canonical_rows",
    "metric_result_sets",
    "metric_results",
    "metric_result_inputs",
    "metric_result_currencies",
    "analysis_results",
    "analysis_result_items",
    "analysis_item_metric_references",
    "analysis_item_claim_references",
    "report_versions",
)
