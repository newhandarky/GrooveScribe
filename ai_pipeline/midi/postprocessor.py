from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ai_pipeline.midi.errors import NoUsableDrumEventsError, ProcessedMidiInvalidError
from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.quality import quality_diagnostics
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
        deduped_events, dedupe_warnings = self._dedupe_events(quantized_events)
        filtered_events, filter_summary = self._apply_tom_false_positive_filter(deduped_events)
        filter_warnings = self._filter_warnings(filter_summary)
        if not deduped_events:
            raise NoUsableDrumEventsError("no MIDI note events survived mapping, filtering, and dedupe")
        if not filtered_events:
            raise NoUsableDrumEventsError("no MIDI note events survived tom false-positive filtering")

        estimated_bpm = midi_data.tempo_bpm or DEFAULT_TEMPO_BPM
        processed_midi_path = output_dir / "processed_drum.mid"
        drum_events_path = output_dir / "drum_events.json"

        write_drum_midi(
            processed_midi_path,
            tuple(filtered_events),
            ticks_per_beat=midi_data.ticks_per_beat,
            tempo_bpm=estimated_bpm,
            time_signature=midi_data.time_signature,
            default_duration_ticks=self.config.default_duration_ticks,
        )
        self._validate_processed_midi(processed_midi_path)

        raw_note_histogram = Counter(event.note for event in midi_data.notes)
        processed_drum_counts = Counter(event.drum for event in filtered_events)
        quality_warnings = self._quality_warnings(
            input_event_count=len(midi_data.notes),
            output_event_count=len(filtered_events),
            dropped_event_count=len(midi_data.notes) - len(filtered_events),
            raw_note_histogram=raw_note_histogram,
            processed_drum_counts=processed_drum_counts,
        )
        report = MidiPostProcessReport(
            input_event_count=len(midi_data.notes),
            output_event_count=len(filtered_events),
            dropped_event_count=len(midi_data.notes) - len(filtered_events),
            quantize_grid=self.config.quantize_grid,
            estimated_bpm=estimated_bpm,
            time_signature=midi_data.time_signature,
            warnings=tuple(sorted(mapping_warnings | dedupe_warnings | filter_warnings | quality_warnings)),
            raw_note_histogram=dict(sorted(raw_note_histogram.items())),
            processed_drum_counts=dict(sorted(processed_drum_counts.items())),
            postprocess_filters={"tom_false_positive": filter_summary},
        )
        drum_events_path.write_text(
            json.dumps(
                self._build_events_payload(filtered_events, midi_data.ticks_per_beat, report),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return MidiPostProcessResult(
            processed_midi_path=processed_midi_path,
            drum_events_path=drum_events_path,
            events=tuple(filtered_events),
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

    def _dedupe_events(self, events: list[ProcessedDrumEvent]) -> tuple[list[ProcessedDrumEvent], set[str]]:
        deduped: list[ProcessedDrumEvent] = []
        warnings: set[str] = set()
        for event in sorted(events, key=lambda item: (item.note, item.tick, -item.velocity)):
            if deduped and deduped[-1].note == event.note:
                previous = deduped[-1]
                if event.tick - previous.tick <= self.config.dedupe_window_ticks:
                    warnings.add("repeated_close_events_deduped")
                    if event.velocity > previous.velocity:
                        deduped[-1] = event
                    continue
            deduped.append(event)
        return sorted(deduped, key=lambda item: (item.tick, item.note)), warnings

    def _apply_tom_false_positive_filter(
        self,
        events: list[ProcessedDrumEvent],
    ) -> tuple[list[ProcessedDrumEvent], dict]:
        summary = self._tom_filter_summary(events, events, status="disabled")
        if not self.config.tom_filter_enabled:
            return events, summary

        summary["enabled"] = True
        summary["preset"] = self.config.tom_filter_preset
        if self.config.tom_filter_preset != "tom_guard_v1":
            summary["status"] = "unsupported_preset"
            return events, summary

        counts = Counter(event.drum for event in events)
        core_present = counts.get("kick", 0) > 0 and counts.get("snare", 0) > 0 and self._hihat_count(counts) > 0
        if not core_present:
            summary["status"] = "skipped_missing_core_groove"
            return events, summary

        tom_count = counts.get("tom", 0)
        event_count = len(events)
        if not event_count or tom_count / event_count <= self.config.tom_filter_target_max_ratio:
            summary["status"] = "no_op_ratio_within_target"
            return events, summary

        drop_needed = 0
        while drop_needed < tom_count:
            remaining_tom = tom_count - drop_needed
            remaining_events = event_count - drop_needed
            if remaining_events and remaining_tom / remaining_events <= self.config.tom_filter_target_max_ratio:
                break
            drop_needed += 1
        if drop_needed <= 0:
            summary["status"] = "no_op_ratio_within_target"
            return events, summary

        tom_candidates = [event for event in events if event.drum == "tom"]
        core_events = [event for event in events if event.drum in {"kick", "snare", "closed_hat", "pedal_hat", "open_hat"}]
        ranked_toms = sorted(
            tom_candidates,
            key=lambda event: (
                self._nearest_core_distance(event, core_events),
                event.velocity,
                event.tick,
            ),
        )
        droppable = [
            event
            for event in ranked_toms
            if self._nearest_core_distance(event, core_events) <= self.config.tom_filter_core_overlap_window_ticks
        ]
        if not droppable:
            summary["status"] = "no_safe_tom_filter_change"
            return events, summary

        drop_ids = {id(event) for event in droppable[:drop_needed]}
        filtered = [event for event in events if id(event) not in drop_ids]
        if filtered == events:
            summary["status"] = "no_safe_tom_filter_change"
            return events, summary
        return filtered, self._tom_filter_summary(events, filtered, status="applied")

    def _tom_filter_summary(
        self,
        input_events: list[ProcessedDrumEvent],
        output_events: list[ProcessedDrumEvent],
        *,
        status: str,
    ) -> dict:
        input_counts = Counter(event.drum for event in input_events)
        output_counts = Counter(event.drum for event in output_events)
        input_tom_count = input_counts.get("tom", 0)
        output_tom_count = output_counts.get("tom", 0)
        return {
            "enabled": self.config.tom_filter_enabled,
            "preset": self.config.tom_filter_preset,
            "status": status,
            "input_tom_count": input_tom_count,
            "output_tom_count": output_tom_count,
            "dropped_tom_count": max(0, input_tom_count - output_tom_count),
            "target_max_tom_ratio": self.config.tom_filter_target_max_ratio,
            "input_event_count": len(input_events),
            "output_event_count": len(output_events),
        }

    def _filter_warnings(self, summary: dict) -> set[str]:
        status = str(summary.get("status") or "")
        if status in {"no_safe_tom_filter_change", "unsupported_preset"}:
            return {status}
        return set()

    def _nearest_core_distance(
        self,
        event: ProcessedDrumEvent,
        core_events: list[ProcessedDrumEvent],
    ) -> int:
        if not core_events:
            return 1_000_000
        return min(abs(event.tick - core_event.tick) for core_event in core_events)

    def _hihat_count(self, counts: Counter[str]) -> int:
        return sum(counts.get(drum, 0) for drum in ("closed_hat", "pedal_hat", "open_hat"))

    def _validate_processed_midi(self, processed_midi_path: Path) -> None:
        try:
            event_count = count_note_on_events(processed_midi_path)
        except Exception as exc:
            raise ProcessedMidiInvalidError(str(exc)) from exc
        if event_count <= 0:
            raise ProcessedMidiInvalidError("processed MIDI contains no note-on events")

    def _quality_warnings(
        self,
        *,
        input_event_count: int,
        output_event_count: int,
        dropped_event_count: int,
        raw_note_histogram: Counter[int],
        processed_drum_counts: Counter[str],
    ) -> set[str]:
        warnings: set[str] = set()
        warnings.update(
            quality_diagnostics(
                raw_note_histogram=raw_note_histogram,
                processed_drum_counts=processed_drum_counts,
                raw_event_count=input_event_count,
                processed_event_count=output_event_count,
            )
        )
        if input_event_count and dropped_event_count / input_event_count >= 0.5:
            warnings.add("high_drop_ratio")
        return warnings

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
            "raw_note_histogram": {str(key): value for key, value in (report.raw_note_histogram or {}).items()},
            "processed_drum_counts": report.processed_drum_counts or {},
            "postprocess_filters": report.postprocess_filters or {},
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
