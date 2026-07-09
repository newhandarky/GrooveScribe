from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.transcription_job import TranscriptionJob
    from app.models.user import User


class AudioFile(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "audio_files"

    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    user: Mapped["User | None"] = relationship(back_populates="audio_files")
    transcription_jobs: Mapped[list["TranscriptionJob"]] = relationship(back_populates="audio_file")
