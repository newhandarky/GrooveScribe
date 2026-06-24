from __future__ import annotations

from pathlib import Path

from ai_pipeline.midi.errors import RawMidiInvalidError
from ai_pipeline.midi.types import MidiData, ProcessedDrumEvent, RawMidiNoteEvent

DEFAULT_TEMPO_BPM = 120.0
DEFAULT_TIME_SIGNATURE = "4/4"


def parse_midi(path: Path) -> MidiData:
    data = path.read_bytes()
    if len(data) < 14 or data[:4] != b"MThd":
        raise RawMidiInvalidError("missing MIDI header chunk")

    header_length = int.from_bytes(data[4:8], "big")
    if header_length < 6 or len(data) < 8 + header_length:
        raise RawMidiInvalidError("invalid MIDI header chunk")

    midi_format = int.from_bytes(data[8:10], "big")
    track_count = int.from_bytes(data[10:12], "big")
    division = int.from_bytes(data[12:14], "big")
    if midi_format not in (0, 1):
        raise RawMidiInvalidError(f"unsupported MIDI format: {midi_format}")
    if division & 0x8000:
        raise RawMidiInvalidError("SMPTE time division is not supported in MVP")

    offset = 8 + header_length
    notes: list[RawMidiNoteEvent] = []
    tempo_bpm: float | None = None
    time_signature = DEFAULT_TIME_SIGNATURE

    for _ in range(track_count):
        if offset + 8 > len(data) or data[offset : offset + 4] != b"MTrk":
            raise RawMidiInvalidError("missing MIDI track chunk")
        track_length = int.from_bytes(data[offset + 4 : offset + 8], "big")
        track_start = offset + 8
        track_end = track_start + track_length
        if track_end > len(data):
            raise RawMidiInvalidError("MIDI track length exceeds file size")
        track_notes, track_tempo, track_sig = _parse_track(data[track_start:track_end])
        notes.extend(track_notes)
        if tempo_bpm is None and track_tempo is not None:
            tempo_bpm = track_tempo
        if track_sig != DEFAULT_TIME_SIGNATURE:
            time_signature = track_sig
        offset = track_end

    return MidiData(
        ticks_per_beat=division,
        notes=tuple(sorted(notes, key=lambda event: (event.tick, event.note))),
        tempo_bpm=tempo_bpm,
        time_signature=time_signature,
    )


def write_drum_midi(
    path: Path,
    events: tuple[ProcessedDrumEvent, ...],
    ticks_per_beat: int,
    tempo_bpm: float = DEFAULT_TEMPO_BPM,
    time_signature: str = DEFAULT_TIME_SIGNATURE,
    default_duration_ticks: int = 120,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    track_events: list[tuple[int, bytes]] = []

    tempo_microseconds = int(60_000_000 / tempo_bpm)
    track_events.append((0, bytes([0xFF, 0x51, 0x03]) + tempo_microseconds.to_bytes(3, "big")))
    numerator, denominator = _parse_time_signature(time_signature)
    denominator_power = 0
    value = denominator
    while value > 1:
        value //= 2
        denominator_power += 1
    track_events.append((0, bytes([0xFF, 0x58, 0x04, numerator, denominator_power, 24, 8])))

    for event in sorted(events, key=lambda item: (item.tick, item.note)):
        note_on = bytes([0x99, event.note, max(1, min(127, event.velocity))])
        note_off = bytes([0x89, event.note, 0])
        track_events.append((event.tick, note_on))
        track_events.append((event.tick + default_duration_ticks, note_off))

    track_events.sort(key=lambda item: (item[0], 0 if item[1][0] == 0x89 else 1))
    track = bytearray()
    previous_tick = 0
    for tick, payload in track_events:
        delta = max(0, tick - previous_tick)
        track.extend(_write_variable_length(delta))
        track.extend(payload)
        previous_tick = tick
    track.extend(bytes([0x00, 0xFF, 0x2F, 0x00]))

    output = bytearray()
    output.extend(b"MThd")
    output.extend((6).to_bytes(4, "big"))
    output.extend((0).to_bytes(2, "big"))
    output.extend((1).to_bytes(2, "big"))
    output.extend(ticks_per_beat.to_bytes(2, "big"))
    output.extend(b"MTrk")
    output.extend(len(track).to_bytes(4, "big"))
    output.extend(track)
    path.write_bytes(bytes(output))


def _parse_track(track_data: bytes) -> tuple[list[RawMidiNoteEvent], float | None, str]:
    offset = 0
    tick = 0
    running_status: int | None = None
    notes: list[RawMidiNoteEvent] = []
    tempo_bpm: float | None = None
    time_signature = DEFAULT_TIME_SIGNATURE

    while offset < len(track_data):
        delta, offset = _read_variable_length(track_data, offset)
        tick += delta
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
            channel = status & 0x0F
            data_len = 1 if event_type in (0xC0, 0xD0) else 2
            if offset + data_len > len(track_data):
                raise RawMidiInvalidError("MIDI channel event is truncated")
            event_data = track_data[offset : offset + data_len]
            offset += data_len
            if event_type == 0x90 and data_len == 2 and event_data[1] > 0:
                notes.append(
                    RawMidiNoteEvent(
                        tick=tick,
                        note=event_data[0],
                        velocity=event_data[1],
                        channel=channel,
                    )
                )
            continue

        if status == 0xFF:
            if offset >= len(track_data):
                raise RawMidiInvalidError("MIDI meta event is truncated")
            meta_type = track_data[offset]
            offset += 1
            length, offset = _read_variable_length(track_data, offset)
            payload = track_data[offset : offset + length]
            offset += length
            if len(payload) != length:
                raise RawMidiInvalidError("MIDI meta event length exceeds track size")
            if meta_type == 0x51 and length == 3:
                microseconds = int.from_bytes(payload, "big")
                if microseconds > 0:
                    tempo_bpm = 60_000_000 / microseconds
            elif meta_type == 0x58 and length >= 2:
                denominator = 2 ** payload[1]
                time_signature = f"{payload[0]}/{denominator}"
            continue

        if status in (0xF0, 0xF7):
            length, offset = _read_variable_length(track_data, offset)
            offset += length
            if offset > len(track_data):
                raise RawMidiInvalidError("MIDI sysex event length exceeds track size")
            continue

        raise RawMidiInvalidError(f"unsupported MIDI status byte: {status:#x}")

    return notes, tempo_bpm, time_signature


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


def _write_variable_length(value: int) -> bytes:
    if value < 0:
        raise ValueError("variable-length value must be non-negative")
    buffer = value & 0x7F
    value >>= 7
    while value:
        buffer <<= 8
        buffer |= ((value & 0x7F) | 0x80)
        value >>= 7

    output = bytearray()
    while True:
        output.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            break
    return bytes(output)


def _parse_time_signature(value: str) -> tuple[int, int]:
    try:
        numerator_text, denominator_text = value.split("/", 1)
        return int(numerator_text), int(denominator_text)
    except (ValueError, TypeError):
        return 4, 4
