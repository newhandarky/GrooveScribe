"""initial schema

Revision ID: 20260625_0001
Revises:
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "20260625_0001"
down_revision = None
branch_labels = None
depends_on = None

job_status = sa.Enum(
    "uploaded",
    "queued",
    "processing",
    "completed",
    "failed",
    "interrupted",
    "canceled",
    name="job_status",
)
pipeline_stage = sa.Enum(
    "uploaded",
    "queued",
    "preprocessing",
    "source_separation",
    "stem_validation",
    "drum_transcription",
    "midi_post_processing",
    "notation_generation",
    "pdf_export",
    "completed",
    "failed",
    name="pipeline_stage",
)
confidence_label = sa.Enum("low", "medium", "high", name="confidence_label")
export_file_type = sa.Enum("midi", "musicxml", "pdf", name="export_file_type")
export_file_status = sa.Enum("pending", "available", "failed", name="export_file_status")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "audio_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("original_storage_key", sa.String(length=1024), nullable=False),
        sa.Column("normalized_storage_key", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audio_files_user_id", "audio_files", ["user_id"])

    op.create_table(
        "transcription_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("audio_file_id", sa.String(length=36), nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="uploaded"),
        sa.Column("stage", pipeline_stage, nullable=False, server_default="uploaded"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("pipeline_version", sa.String(length=64), nullable=False, server_default="poc-local-v1"),
        sa.Column("source_separator", sa.String(length=128), nullable=True),
        sa.Column("source_separator_version", sa.String(length=128), nullable=True),
        sa.Column("drum_transcriber", sa.String(length=128), nullable=True),
        sa.Column("drum_transcriber_version", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_stage", sa.String(length=128), nullable=True),
        sa.Column("internal_error_ref", sa.String(length=1024), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["audio_file_id"], ["audio_files.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transcription_jobs_audio_file_id", "transcription_jobs", ["audio_file_id"])
    op.create_index("ix_transcription_jobs_stage", "transcription_jobs", ["stage"])
    op.create_index("ix_transcription_jobs_status", "transcription_jobs", ["status"])
    op.create_index("ix_transcription_jobs_user_id", "transcription_jobs", ["user_id"])

    op.create_table(
        "drum_tracks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("drums_stem_storage_key", sa.String(length=1024), nullable=True),
        sa.Column("raw_midi_storage_key", sa.String(length=1024), nullable=True),
        sa.Column("processed_midi_storage_key", sa.String(length=1024), nullable=True),
        sa.Column("drum_events_storage_key", sa.String(length=1024), nullable=True),
        sa.Column("estimated_bpm", sa.Float(), nullable=True),
        sa.Column("time_signature", sa.String(length=16), nullable=False, server_default="4/4"),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence_label", confidence_label, nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["transcription_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_drum_tracks_job_id", "drum_tracks", ["job_id"])

    op.create_table(
        "export_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("type", export_file_type, nullable=False),
        sa.Column("status", export_file_status, nullable=False, server_default="pending"),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["transcription_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_export_files_job_id", "export_files", ["job_id"])
    op.create_index("ix_export_files_status", "export_files", ["status"])
    op.create_index("ix_export_files_type", "export_files", ["type"])


def downgrade() -> None:
    op.drop_index("ix_export_files_type", table_name="export_files")
    op.drop_index("ix_export_files_status", table_name="export_files")
    op.drop_index("ix_export_files_job_id", table_name="export_files")
    op.drop_table("export_files")
    op.drop_index("ix_drum_tracks_job_id", table_name="drum_tracks")
    op.drop_table("drum_tracks")
    op.drop_index("ix_transcription_jobs_user_id", table_name="transcription_jobs")
    op.drop_index("ix_transcription_jobs_status", table_name="transcription_jobs")
    op.drop_index("ix_transcription_jobs_stage", table_name="transcription_jobs")
    op.drop_index("ix_transcription_jobs_audio_file_id", table_name="transcription_jobs")
    op.drop_table("transcription_jobs")
    op.drop_index("ix_audio_files_user_id", table_name="audio_files")
    op.drop_table("audio_files")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    bind = op.get_bind()
    export_file_status.drop(bind, checkfirst=True)
    export_file_type.drop(bind, checkfirst=True)
    confidence_label.drop(bind, checkfirst=True)
    pipeline_stage.drop(bind, checkfirst=True)
    job_status.drop(bind, checkfirst=True)
