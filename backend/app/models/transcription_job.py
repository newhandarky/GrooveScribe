from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import JobStatus, PipelineStage
from app.models.mixins import TimestampMixin, UuidPrimaryKeyMixin


class TranscriptionJob(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "transcription_jobs"

    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    audio_file_id: Mapped[str] = mapped_column(ForeignKey("audio_files.id"), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", values_callable=lambda enum: [item.value for item in enum]),
        default=JobStatus.UPLOADED,
        nullable=False,
        index=True,
    )
    stage: Mapped[PipelineStage] = mapped_column(
        Enum(PipelineStage, name="pipeline_stage", values_callable=lambda enum: [item.value for item in enum]),
        default=PipelineStage.UPLOADED,
        nullable=False,
        index=True,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pipeline_version: Mapped[str] = mapped_column(String(64), default="poc-local-v1", nullable=False)
    source_separator: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_separator_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    drum_transcriber: Mapped[str | None] = mapped_column(String(128), nullable=True)
    drum_transcriber_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_stage: Mapped[str | None] = mapped_column(String(128), nullable=True)
    internal_error_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User | None"] = relationship(back_populates="transcription_jobs")
    audio_file: Mapped["AudioFile"] = relationship(back_populates="transcription_jobs")
    drum_track: Mapped["DrumTrack | None"] = relationship(back_populates="job", uselist=False)
    export_files: Mapped[list["ExportFile"]] = relationship(back_populates="job")
