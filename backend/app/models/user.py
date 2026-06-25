from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UuidPrimaryKeyMixin


class User(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    audio_files: Mapped[list["AudioFile"]] = relationship(back_populates="user")
    transcription_jobs: Mapped[list["TranscriptionJob"]] = relationship(back_populates="user")
