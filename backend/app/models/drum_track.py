from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import ConfidenceLabel
from app.models.mixins import CreatedAtMixin, UuidPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.transcription_job import TranscriptionJob


class DrumTrack(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "drum_tracks"

    job_id: Mapped[str] = mapped_column(ForeignKey("transcription_jobs.id"), nullable=False, unique=True, index=True)
    drums_stem_storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    raw_midi_storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    processed_midi_storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    drum_events_storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    estimated_bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_signature: Mapped[str] = mapped_column(String(16), default="4/4", nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence_label: Mapped[ConfidenceLabel | None] = mapped_column(
        Enum(ConfidenceLabel, name="confidence_label", values_callable=lambda enum: [item.value for item in enum]),
        nullable=True,
    )
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    job: Mapped["TranscriptionJob"] = relationship(back_populates="drum_track")
