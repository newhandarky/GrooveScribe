from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ExportFileStatus, ExportFileType
from app.models.mixins import CreatedAtMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.transcription_job import TranscriptionJob


class ExportFile(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "export_files"

    job_id: Mapped[str] = mapped_column(ForeignKey("transcription_jobs.id"), nullable=False, index=True)
    type: Mapped[ExportFileType] = mapped_column(
        Enum(ExportFileType, name="export_file_type", values_callable=lambda enum: [item.value for item in enum]),
        nullable=False,
        index=True,
    )
    status: Mapped[ExportFileStatus] = mapped_column(
        Enum(ExportFileStatus, name="export_file_status", values_callable=lambda enum: [item.value for item in enum]),
        default=ExportFileStatus.PENDING,
        nullable=False,
        index=True,
    )
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)

    job: Mapped["TranscriptionJob"] = relationship(back_populates="export_files")
