from __future__ import annotations

import json
from pathlib import Path

from ai_pipeline.midi.errors import NoUsableDrumEventsError, ProcessedMidiInvalidError
from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.simple_midi import DEFAULT_TEMPO_BPM, parse_midi, write_drum_midi
from ai_pipeline.midi.types import (
    MidiPostProcessConfig,
    MidiPostProcessReport,
    MidiPostProcessResult,
    ProcessedDrumEvent,
)
from ai_pipeline.transcription.midi_validation import count_note_on_events


class MidiPostProcessor:
    def __init__(self, config: MidiPostProcessConfig | None = None) -> None:
        self.config = config or MidiPostProcessConfig()

    def process(self, raw_midi_path: Path, output_dir: Path) -> MidiPostProcessResult:
        midi_data = parse_midi(raw_midi_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        mapped_events, mapping_warnings = self._map_and_filter_events(midi_data.notes)
        quantized_events = self._quantize_events(mapped_events, midi_data.ticks_per_beat)
        deduped_events = self._dedupe_events(quantized_events)
        if not deduped_events:
            raise NoUsableDrumEventsError("no MIDI note events survived mapping, filtering, and dedupe")

        estimated_bpm = midi_data.tempo_bpm or DEFAULT_TEMPO_BPM
        processed_midi_path = output_dir / "processed_drum.mid"
        drum_events_path = output_dir / "drum_events.json"

        write_drum_midi(
            processed_midi_path,
            tuple(deduped_events),
            ticks_per_beat=midi_data.ticks_per_beat,
            tempo_bpm=estimated_bpm,
            time_signature=midi_data.time_signature,
            default_duration_ticks=self.config.default_duration_ticks,
        )
        self._validate_processed_midi(processed_midi_path)

        report = MidiPostProcessReport(
            input_event_count=len(midi_data.notes),
            output_event_count=len(deduped_events),
            dropped_event_count=len(midi_data.notes) - len(deduped_events),
            quantize_grid=self.config.quantize_grid,
            estimated_bpm=estimated_bpm,
            time_signature=midi_data.time_signature,
            warnings=tuple(sorted(mapping_warnings)),
        )
        drum_events_path.write_text(
            json.dumps(
                self._build_events_payload(deduped_events, midi_data.ticks_per_beat, report),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return MidiPostProcessResult(
            processed_midi_path=processed_midi_path,
            drum_events_path=drum_events_path,
            events=tuple(deduped_events),
            report=report,
        )

    def _map_and_filter_events(self, events) -> tuple[list[ProcessedDrumEvent], set[str]]:
        processed: list[ProcessedDrumEvent] = []
        warnings: set[str] = set()
        for event in events:
            if event.velocity < self.config.velocity_floor:
                warnings.add("velocity_floor_filtered")
                continue
            mapping = map_to_general_midi_drum(event.note)
            if mapping is None:
                warnings.add("unknown_drum_notes_dropped")
                continue
            processed.append(
                ProcessedDrumEvent(
                    tick=event.tick,
                    note=mapping.note,
                    drum=mapping.drum,
                    velocity=max(1, min(127, event.velocity)),
                )
            )
        return processed, warnings

    def _quantize_events(
        self,
        events: list[ProcessedDrumEvent],
        ticks_per_beat: int,
    ) -> list[ProcessedDrumEvent]:
        grid_ticks = max(1, round(ticks_per_beat / self.config.grid_subdivisions_per_beat))
        quantized: list[ProcessedDrumEvent] = []
        for event in events:
            tick = round(event.tick / grid_ticks) * grid_ticks
            quantized.append(
                ProcessedDrumEvent(
                    tick=max(0, tick),
                    note=event.note,
                    drum=event.drum,
                    velocity=event.velocity,
                )
            )
        return sorted(quantized, key=lambda item: (item.tick, item.note, -item.velocity))

    def _dedupe_events(self, events: list[ProcessedDrumEvent]) -> list[ProcessedDrumEvent]:
        deduped: list[ProcessedDrumEvent] = []
        for event in sorted(events, key=lambda item: (item.note, item.tick, -item.velocity)):
            if deduped and deduped[-1].note == event.note:
                previous = deduped[-1]
                if event.tick - previous.tick <= self.config.dedupe_window_ticks:
                    if event.velocity > previous.velocity:
                        deduped[-1] = event
                    continue
            deduped.append(event)
        return sorted(deduped, key=lambda item: (item.tick, item.note))

    def _validate_processed_midi(self, processed_midi_path: Path) -> None:
        try:
            event_count = count_note_on_events(processed_midi_path)
        except Exception as exc:
            raise ProcessedMidiInvalidError(str(exc)) from exc
        if event_count <= 0:
            raise ProcessedMidiInvalidError("processed MIDI contains no note-on events")

    def _build_events_payload(
        self,
        events: list[ProcessedDrumEvent],
        ticks_per_beat: int,
        report: MidiPostProcessReport,
    ) -> dict:
        return {
            "schema_version": "1.0",
            "ticks_per_beat": ticks_per_beat,
            "estimated_bpm": report.estimated_bpm,
            "time_signature": report.time_signature,
            "quantize_grid": report.quantize_grid,
            "event_count": len(events),
            "warnings": list(report.warnings),
            "events": [
                {
                    "index": index,
                    "tick": event.tick,
                    "beat": event.tick / ticks_per_beat,
                    "drum": event.drum,
                    "midi_note": event.note,
                    "velocity": event.velocity,
                }
                for index, event in enumerate(events)
            ],
        }
