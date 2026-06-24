from __future__ import annotations

from pathlib import Path

from ai_pipeline.transcription.errors import RawMidiInvalidError, RawMidiNotFoundError


def count_note_on_events(midi_path: Path) -> int:
    if not midi_path.exists() or midi_path.stat().st_size == 0:
        raise RawMidiNotFoundError(f"raw MIDI is missing or empty: {midi_path}")

    data = midi_path.read_bytes()
    if len(data) < 14 or data[:4] != b"MThd":
        raise RawMidiInvalidError("missing MIDI header chunk")

    header_length = int.from_bytes(data[4:8], "big")
    if header_length < 6:
        raise RawMidiInvalidError("invalid MIDI header length")

    offset = 8 + header_length
    event_count = 0
    while offset < len(data):
        if offset + 8 > len(data) or data[offset : offset + 4] != b"MTrk":
            raise RawMidiInvalidError("missing MIDI track chunk")
        track_length = int.from_bytes(data[offset + 4 : offset + 8], "big")
        track_start = offset + 8
        track_end = track_start + track_length
        if track_end > len(data):
            raise RawMidiInvalidError("MIDI track length exceeds file size")
        event_count += _count_note_on_in_track(data[track_start:track_end])
        offset = track_end

    return event_count


def _read_variable_length(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if offset >= len(data):
            raise RawMidiInvalidError("unexpected end of MIDI variable-length value")
        byte = data[offset]
        offset += 1
        value = (value << 7) | (byte & 0x7F)
        if byte < 0x80:
            return value, offset
    raise RawMidiInvalidError("MIDI variable-length value is too long")


def _count_note_on_in_track(track_data: bytes) -> int:
    offset = 0
    running_status: int | None = None
    count = 0

    while offset < len(track_data):
        _, offset = _read_variable_length(track_data, offset)
        if offset >= len(track_data):
            break

        status = track_data[offset]
        if status < 0x80:
            if running_status is None:
                raise RawMidiInvalidError("MIDI running status used before status byte")
            status = running_status
        else:
            offset += 1
            if status < 0xF0:
                running_status = status

        if 0x80 <= status <= 0xEF:
            event_type = status & 0xF0
            data_len = 1 if event_type in (0xC0, 0xD0) else 2
            if offset + data_len > len(track_data):
                raise RawMidiInvalidError("MIDI channel event is truncated")
            event_data = track_data[offset : offset + data_len]
            offset += data_len
            if event_type == 0x90 and data_len == 2 and event_data[1] > 0:
                count += 1
            continue

        if status == 0xFF:
            if offset >= len(track_data):
                raise RawMidiInvalidError("MIDI meta event is truncated")
            offset += 1
            length, offset = _read_variable_length(track_data, offset)
            offset += length
            if offset > len(track_data):
                raise RawMidiInvalidError("MIDI meta event length exceeds track size")
            continue

        if status in (0xF0, 0xF7):
            length, offset = _read_variable_length(track_data, offset)
            offset += length
            if offset > len(track_data):
                raise RawMidiInvalidError("MIDI sysex event length exceeds track size")
            continue

        raise RawMidiInvalidError(f"unsupported MIDI status byte: {status:#x}")

    return count
