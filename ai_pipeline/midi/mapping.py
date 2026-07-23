from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class DrumMappingResult:
    note: int
    drum: str
    articulation: str | None = None


KICK_NOTES = {35, 36}
SNARE_NOTES = {37, 38, 39, 40}
CLOSED_HAT_NOTES = {42}
PEDAL_HAT_NOTES = {44}
OPEN_HAT_NOTES = {46}
TOM_NOTES = {41, 43, 45, 47, 48, 50}
CYMBAL_NOTES = {49, 51, 52, 55, 57, 59}
LEGACY_HI_HAT_DRUMS = frozenset({"closed_hat", "open_hat", "pedal_hat"})


def normalize_drum_name(drum: str) -> str:
    """Collapse legacy hi-hat articulations into the public generic class."""
    return "hi_hat" if drum in LEGACY_HI_HAT_DRUMS else drum


def normalize_drum_counts(drum_counts: Mapping[str, int]) -> dict[str, int]:
    """Read legacy count artifacts while emitting only canonical drum labels."""
    normalized: dict[str, int] = {}
    for drum, count in drum_counts.items():
        canonical = normalize_drum_name(str(drum))
        normalized[canonical] = normalized.get(canonical, 0) + int(count)
    return normalized


def map_to_general_midi_drum(note: int) -> DrumMappingResult | None:
    if note in KICK_NOTES:
        return DrumMappingResult(note=36, drum="kick")
    if note in SNARE_NOTES:
        return DrumMappingResult(note=38, drum="snare")
    if note in CLOSED_HAT_NOTES | PEDAL_HAT_NOTES | OPEN_HAT_NOTES:
        # MIDI pitches encode an articulation convention, not a product-level
        # inference result. Collapse them into the supported generic hi-hat hit.
        return DrumMappingResult(note=42, drum="hi_hat")
    if note in TOM_NOTES:
        return DrumMappingResult(note=45, drum="tom")
    if note in CYMBAL_NOTES:
        return DrumMappingResult(note=49, drum="cymbal")
    return None
