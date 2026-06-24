from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DrumMappingResult:
    note: int
    drum: str


KICK_NOTES = {35, 36}
SNARE_NOTES = {37, 38, 39, 40}
CLOSED_HAT_NOTES = {42}
PEDAL_HAT_NOTES = {44}
OPEN_HAT_NOTES = {46}
TOM_NOTES = {41, 43, 45, 47, 48, 50}
CYMBAL_NOTES = {49, 51, 52, 55, 57, 59}


def map_to_general_midi_drum(note: int) -> DrumMappingResult | None:
    if note in KICK_NOTES:
        return DrumMappingResult(note=36, drum="kick")
    if note in SNARE_NOTES:
        return DrumMappingResult(note=38, drum="snare")
    if note in CLOSED_HAT_NOTES:
        return DrumMappingResult(note=42, drum="closed_hat")
    if note in PEDAL_HAT_NOTES:
        return DrumMappingResult(note=44, drum="pedal_hat")
    if note in OPEN_HAT_NOTES:
        return DrumMappingResult(note=46, drum="open_hat")
    if note in TOM_NOTES:
        return DrumMappingResult(note=45, drum="tom")
    if note in CYMBAL_NOTES:
        return DrumMappingResult(note=49, drum="cymbal")
    return None
