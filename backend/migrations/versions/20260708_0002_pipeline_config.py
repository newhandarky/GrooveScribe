"""add per-job pipeline config

Revision ID: 20260708_0002
Revises: 20260625_0001
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = "20260708_0002"
down_revision = "20260625_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transcription_jobs", sa.Column("pipeline_mode", sa.String(length=32), nullable=True))
    op.add_column("transcription_jobs", sa.Column("adtof_threshold_preset", sa.String(length=64), nullable=True))
    op.add_column("transcription_jobs", sa.Column("tom_filter_preset", sa.String(length=64), nullable=True))
    op.add_column("transcription_jobs", sa.Column("runtime_fallback_status", sa.String(length=64), nullable=True))
    op.add_column("transcription_jobs", sa.Column("source_job_id", sa.String(length=36), nullable=True))
    op.create_index("ix_transcription_jobs_source_job_id", "transcription_jobs", ["source_job_id"])


def downgrade() -> None:
    op.drop_index("ix_transcription_jobs_source_job_id", table_name="transcription_jobs")
    op.drop_column("transcription_jobs", "source_job_id")
    op.drop_column("transcription_jobs", "runtime_fallback_status")
    op.drop_column("transcription_jobs", "tom_filter_preset")
    op.drop_column("transcription_jobs", "adtof_threshold_preset")
    op.drop_column("transcription_jobs", "pipeline_mode")
