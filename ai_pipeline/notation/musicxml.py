from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ai_pipeline.notation.errors import MusicXmlInvalidError, NotationGenerationFailedError
from ai_pipeline.notation.types import MusicXmlResult, NotationConfig
from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.mapping import DRUM_TAXONOMY_ID, canonical_drum_name
from ai_pipeline.midi.types import ProcessedDrumEvent

HAND_VOICE = "1"
FOOT_VOICE = "2"


@dataclass(frozen=True)
class DrumDisplay:
    display_step: str
    display_octave: int
    notehead: str
    voice: str
    stem: str
    midi_note: int
    instrument_id: str
    instrument_name: str


@dataclass(frozen=True)
class ChartMeasure:
    """A human-facing measure derived from full processed transcription events."""

    index: int
    render_kind: str
    events: tuple[dict, ...]
    source_events: tuple[dict, ...] = ()


DRUM_DISPLAYS = {
    "kick": DrumDisplay("F", 4, "normal", FOOT_VOICE, "down", 36, "P1-I36", "Bass Drum 1"),
    "snare": DrumDisplay("C", 5, "normal", HAND_VOICE, "up", 38, "P1-I38", "Acoustic Snare"),
    "hi_hat": DrumDisplay("G", 5, "x", HAND_VOICE, "up", 42, "P1-I42", "Hi-hat"),
    "tom": DrumDisplay("D", 5, "normal", HAND_VOICE, "up", 45, "P1-I45", "Low Tom"),
    "cymbal": DrumDisplay("A", 5, "x", HAND_VOICE, "up", 49, "P1-I49", "Crash Cymbal 1"),
}


class MusicXmlGenerator:
    def __init__(self, config: NotationConfig | None = None) -> None:
        self.config = config or NotationConfig()

    def generate(self, drum_events_path: Path, output_dir: Path) -> MusicXmlResult:
        try:
            payload = json.loads(drum_events_path.read_text(encoding="utf-8"))
            events = payload.get("events", [])
            ticks_per_beat = int(payload.get("ticks_per_beat", 480))
            estimated_bpm = float(payload.get("estimated_bpm", 120.0))
            time_signature = str(payload.get("time_signature", "4/4"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise NotationGenerationFailedError(str(exc)) from exc

        if not events:
            raise NotationGenerationFailedError("drum_events.json contains no events")

        output_dir.mkdir(parents=True, exist_ok=True)
        musicxml_path = output_dir / "score.musicxml"
        chart_events, chart_summary = _build_chart_events(
            events,
            ticks_per_beat=ticks_per_beat,
            time_signature=time_signature,
            chart_mode=self.config.chart_mode,
            max_events_per_measure=self.config.max_chart_events_per_measure,
        )
        tempo_bpm = self.config.tempo_bpm_override if self.config.tempo_bpm_override is not None else estimated_bpm
        tempo_source = "manual_override" if self.config.tempo_bpm_override is not None else "estimated"
        chart_events_path = output_dir / "chart_events.json"
        root, readability_summary, rhythm_summary = self._build_score(
            chart_events,
            ticks_per_beat,
            tempo_bpm,
            time_signature,
            chart_summary=chart_summary,
        )
        chart_summary.update(rhythm_summary)
        chart_warnings = list(chart_summary.get("warnings", []))
        if chart_summary.get("groove_sixteenth_note_count", 0) or chart_summary.get("measures_with_fragmented_rests", 0):
            chart_warnings.append("notation_fragmented_groove_rhythm")
            if chart_summary.get("readability_verdict") == "readable_chart_candidate":
                chart_summary["readability_verdict"] = "needs_manual_arrangement"
        chart_summary["warnings"] = list(dict.fromkeys(chart_warnings))
        _write_chart_events(
            chart_events_path,
            source_payload=payload,
            chart_events=chart_events,
            chart_summary=chart_summary,
            tempo_bpm=tempo_bpm,
            tempo_source=tempo_source,
        )
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(musicxml_path, encoding="utf-8", xml_declaration=True)
        self._validate_musicxml(musicxml_path)
        performance_musicxml_path = output_dir / "performance_score.musicxml"
        performance_musicxml_path.write_bytes(musicxml_path.read_bytes())
        performance_midi_path = output_dir / "performance_score.mid"
        write_drum_midi(
            performance_midi_path,
            tuple(
                ProcessedDrumEvent(
                    tick=int(event["tick"]),
                    note=_midi_note_for_drum(str(event["drum"])),
                    drum=str(event["drum"]),
                    velocity=int(event.get("velocity", 80)),
                )
                for event in chart_events
            ),
            ticks_per_beat=ticks_per_beat,
            tempo_bpm=tempo_bpm,
            time_signature=time_signature,
        )

        measure_count = len(root.findall("./part/measure"))
        return MusicXmlResult(
            musicxml_path=musicxml_path,
            performance_musicxml_path=performance_musicxml_path,
            performance_midi_path=performance_midi_path,
            chart_events_path=chart_events_path,
            event_count=len(events),
            chart_event_count=len(chart_events),
            measure_count=measure_count,
            title=self.config.title,
            readability_summary=readability_summary,
            chart_summary=chart_summary,
            tempo_bpm=tempo_bpm,
            tempo_source=tempo_source,
        )

    def _build_score(
        self,
        events,
        ticks_per_beat: int,
        estimated_bpm: float,
        time_signature: str,
        *,
        chart_summary: dict | None = None,
    ) -> tuple[ET.Element, dict, dict]:
        beats, beat_type = _parse_time_signature(time_signature)
        measure_ticks = ticks_per_beat * beats * 4 // beat_type
        divisions = self.config.divisions_per_quarter or ticks_per_beat

        normalized_events = []
        for event in events:
            drum = canonical_drum_name(event.get("drum"))
            if drum is None:
                continue
            normalized_events.append(
                {
                    "tick": int(event.get("tick", 0)),
                    "drum": drum,
                    "velocity": int(event.get("velocity", 80)),
                }
            )
        normalized_events.sort(key=lambda item: (item["tick"], item["drum"]))

        last_tick = max((item["tick"] for item in normalized_events), default=0) + ticks_per_beat
        summary_measure_count = int((chart_summary or {}).get("measure_count") or 0)
        measure_count = max(1, summary_measure_count, math.ceil(last_tick / measure_ticks))
        grouped = defaultdict(list)
        for event in normalized_events:
            measure_index = event["tick"] // measure_ticks
            local_tick = event["tick"] % measure_ticks
            grouped[(measure_index, local_tick)].append(event)
        measure_event_counts: dict[int, int] = defaultdict(int)
        for measure_index, local_tick in grouped:
            measure_event_counts[measure_index] += len(grouped[(measure_index, local_tick)])

        score = ET.Element("score-partwise", version="3.1")
        work = ET.SubElement(score, "work")
        ET.SubElement(work, "work-title").text = self.config.title
        identification = ET.SubElement(score, "identification")
        creator = ET.SubElement(identification, "creator", type="composer")
        creator.text = self.config.composer
        part_list = ET.SubElement(score, "part-list")
        score_part = ET.SubElement(part_list, "score-part", id="P1")
        ET.SubElement(score_part, "part-name").text = self.config.part_name
        for display in DRUM_DISPLAYS.values():
            score_instrument = ET.SubElement(score_part, "score-instrument", id=display.instrument_id)
            ET.SubElement(score_instrument, "instrument-name").text = display.instrument_name
            midi_instrument = ET.SubElement(score_part, "midi-instrument", id=display.instrument_id)
            ET.SubElement(midi_instrument, "midi-channel").text = "10"
            ET.SubElement(midi_instrument, "midi-unpitched").text = str(display.midi_note)

        part = ET.SubElement(score, "part", id="P1")
        rhythm_stats: dict[str, int] = defaultdict(int)
        measure_kinds = {
            int(item.get("measure_index", -1)): str(item.get("render_kind", "groove"))
            for item in (chart_summary or {}).get("chart_measures", [])
        }
        for measure_index in range(measure_count):
            measure = ET.SubElement(part, "measure", number=str(measure_index + 1))
            if measure_index == 0:
                attributes = ET.SubElement(measure, "attributes")
                ET.SubElement(attributes, "divisions").text = str(divisions)
                key = ET.SubElement(attributes, "key")
                ET.SubElement(key, "fifths").text = "0"
                time = ET.SubElement(attributes, "time")
                ET.SubElement(time, "beats").text = str(beats)
                ET.SubElement(time, "beat-type").text = str(beat_type)
                clef = ET.SubElement(attributes, "clef")
                ET.SubElement(clef, "sign").text = "percussion"
                ET.SubElement(clef, "line").text = "2"
                staff_details = ET.SubElement(attributes, "staff-details")
                ET.SubElement(staff_details, "staff-lines").text = "5"
                direction = ET.SubElement(measure, "direction", placement="above")
                direction_type = ET.SubElement(direction, "direction-type")
                metronome = ET.SubElement(direction_type, "metronome")
                ET.SubElement(metronome, "beat-unit").text = "quarter"
                ET.SubElement(metronome, "per-minute").text = str(round(estimated_bpm))
                sound = ET.SubElement(direction, "sound")
                sound.set("tempo", str(round(estimated_bpm, 2)))

            hand_events = _events_for_voice(grouped, measure_index, HAND_VOICE)
            foot_events = _events_for_voice(grouped, measure_index, FOOT_VOICE)
            rhythm_mode = "fill" if measure_kinds.get(measure_index) == "fill" else "groove"
            if hand_events:
                hand_hat_ticks = [
                    tick
                    for tick, events_at_tick in hand_events.items()
                    if any(event["drum"] == "hi_hat" for event in events_at_tick)
                ]
                if hand_hat_ticks:
                    rhythm_stats["hihat_eighth_pulse_measure_count" if len(hand_hat_ticks) >= 5 else "hihat_quarter_pulse_measure_count"] += 1
                self._append_voice(
                    measure,
                    hand_events,
                    measure_ticks,
                    ticks_per_beat,
                    rhythm_mode=rhythm_mode,
                    rhythm_stats=rhythm_stats,
                )
            if hand_events and foot_events:
                self._append_backup(measure, measure_ticks)
            if foot_events:
                self._append_voice(
                    measure,
                    foot_events,
                    measure_ticks,
                    ticks_per_beat,
                    rhythm_mode=rhythm_mode,
                    rhythm_stats=rhythm_stats,
                )
            if not hand_events and not foot_events:
                self._append_rest(measure, measure_ticks, HAND_VOICE, ticks_per_beat=ticks_per_beat, rhythm_stats=rhythm_stats)

        rhythm_summary = _rhythm_summary(rhythm_stats)
        rhythm_summary["measures_with_fragmented_rests"] = _fragmented_rest_measure_count(score, measure_kinds)
        return (
            score,
            _readability_summary(
                normalized_events,
                measure_count=measure_count,
                measure_event_counts=measure_event_counts,
                layout_profile=self.config.layout_profile,
            ),
            rhythm_summary,
        )

    def _append_voice(
        self,
        measure: ET.Element,
        events_by_tick: dict[int, list[dict]],
        measure_ticks: int,
        ticks_per_beat: int,
        *,
        rhythm_mode: str,
        rhythm_stats: dict[str, int],
    ) -> None:
        cursor = 0
        beam_map = _beam_map(events_by_tick, ticks_per_beat)
        ticks = sorted(events_by_tick)
        voice = DRUM_DISPLAYS[next(iter(events_by_tick.values()))[0]["drum"]].voice
        hat_ticks = [
            tick
            for tick in ticks
            if any(event["drum"] == "hi_hat" for event in events_by_tick[tick])
        ]
        hat_pulse_duration = ticks_per_beat // 2 if len(hat_ticks) >= 5 else ticks_per_beat
        for index, local_tick in enumerate(ticks):
            if local_tick > cursor:
                self._append_rest(
                    measure,
                    local_tick - cursor,
                    voice,
                    ticks_per_beat=ticks_per_beat,
                    rhythm_stats=rhythm_stats,
                )
            events_at_tick = sorted(events_by_tick[local_tick], key=lambda item: item["drum"])
            next_tick = ticks[index + 1] if index + 1 < len(ticks) else measure_ticks
            duration = _rhythm_note_duration(
                local_tick,
                next_tick,
                measure_ticks,
                ticks_per_beat,
                rhythm_mode=rhythm_mode,
                events=events_at_tick,
                voice=voice,
                hat_pulse_duration=hat_pulse_duration,
            )
            for event_index, event in enumerate(events_at_tick):
                self._append_drum_note(
                    measure,
                    event["drum"],
                    duration,
                    chord=event_index > 0,
                    beam=beam_map.get(local_tick) if event_index == 0 else None,
                    ticks_per_beat=ticks_per_beat,
                    rhythm_stats=rhythm_stats,
                    rhythm_mode=rhythm_mode,
                )
            cursor = max(cursor, local_tick + duration)
        if cursor < measure_ticks:
            self._append_rest(
                measure,
                measure_ticks - cursor,
                voice,
                ticks_per_beat=ticks_per_beat,
                rhythm_stats=rhythm_stats,
            )

    def _append_rest(
        self,
        measure: ET.Element,
        duration: int,
        voice: str,
        *,
        ticks_per_beat: int = 480,
        rhythm_stats: dict[str, int] | None = None,
    ) -> None:
        if duration <= 0:
            return
        for chunk in _rhythm_duration_chunks(duration, ticks_per_beat):
            note = ET.SubElement(measure, "note")
            ET.SubElement(note, "rest")
            ET.SubElement(note, "duration").text = str(chunk)
            ET.SubElement(note, "voice").text = voice
            ET.SubElement(note, "type").text = _duration_type(chunk, ticks_per_beat)
            if rhythm_stats is not None and chunk < ticks_per_beat // 2:
                rhythm_stats["fragmented_rest_chunks"] += 1

    def _append_backup(self, measure: ET.Element, duration: int) -> None:
        backup = ET.SubElement(measure, "backup")
        ET.SubElement(backup, "duration").text = str(duration)

    def _append_drum_note(
        self,
        measure: ET.Element,
        drum: str,
        duration: int,
        chord: bool = False,
        beam: str | None = None,
        *,
        ticks_per_beat: int = 480,
        rhythm_stats: dict[str, int] | None = None,
        rhythm_mode: str = "groove",
    ) -> None:
        display = DRUM_DISPLAYS[drum]
        note = ET.SubElement(measure, "note")
        if chord:
            ET.SubElement(note, "chord")
        unpitched = ET.SubElement(note, "unpitched")
        ET.SubElement(unpitched, "display-step").text = display.display_step
        ET.SubElement(unpitched, "display-octave").text = str(display.display_octave)
        ET.SubElement(note, "duration").text = str(duration)
        ET.SubElement(note, "instrument", id=display.instrument_id)
        ET.SubElement(note, "voice").text = display.voice
        note_type = _duration_type(duration, ticks_per_beat)
        ET.SubElement(note, "type").text = note_type
        ET.SubElement(note, "stem").text = display.stem
        if display.notehead != "normal":
            ET.SubElement(note, "notehead").text = display.notehead
        if beam and note_type in {"eighth", "16th"}:
            ET.SubElement(note, "beam", number="1").text = beam
            if note_type == "16th":
                ET.SubElement(note, "beam", number="2").text = beam
        if rhythm_stats is not None and not chord:
            if rhythm_mode == "fill" and note_type == "16th":
                rhythm_stats["fill_sixteenth_note_count"] += 1
            elif note_type == "eighth":
                rhythm_stats["groove_eighth_note_count"] += 1
            elif note_type == "16th":
                rhythm_stats["groove_sixteenth_note_count"] += 1

    def _validate_musicxml(self, musicxml_path: Path) -> None:
        try:
            root = ET.parse(musicxml_path).getroot()
        except ET.ParseError as exc:
            raise MusicXmlInvalidError(str(exc)) from exc
        if root.tag != "score-partwise" or root.find("./part/measure/note") is None:
            raise MusicXmlInvalidError("MusicXML missing score-partwise notes")


def _parse_time_signature(value: str) -> tuple[int, int]:
    try:
        beats_text, beat_type_text = value.split("/", 1)
        beats = int(beats_text)
        beat_type = int(beat_type_text)
        if beats <= 0 or beat_type <= 0:
            raise ValueError
        return beats, beat_type
    except (ValueError, AttributeError):
        return 4, 4


def _duration_type(duration: int, ticks_per_beat: int = 480) -> str:
    if duration >= ticks_per_beat * 4:
        return "whole"
    if duration >= ticks_per_beat * 2:
        return "half"
    if duration >= ticks_per_beat:
        return "quarter"
    if duration >= ticks_per_beat // 2:
        return "eighth"
    return "16th"


def _rhythm_note_duration(
    local_tick: int,
    next_tick: int,
    measure_ticks: int,
    ticks_per_beat: int,
    *,
    rhythm_mode: str,
    events: list[dict],
    voice: str,
    hat_pulse_duration: int,
) -> int:
    eighth = max(1, ticks_per_beat // 2)
    quarter = max(eighth, ticks_per_beat)
    sixteenth = max(1, ticks_per_beat // 4)
    remaining = max(1, measure_ticks - local_tick)
    gap = max(sixteenth, next_tick - local_tick)
    is_fill_tail = rhythm_mode == "fill" and local_tick >= measure_ticks - 2 * ticks_per_beat
    has_fill_drum = any(event["drum"] in {"tom", "snare"} for event in events)
    if is_fill_tail and has_fill_drum:
        return min(sixteenth, remaining, gap)
    if voice == HAND_VOICE and any(event["drum"] == "hi_hat" for event in events):
        return min(hat_pulse_duration, remaining, gap)
    return min(quarter, remaining, gap)


def _rhythm_duration_chunks(duration: int, ticks_per_beat: int) -> list[int]:
    if duration <= 0:
        return []
    units = [ticks_per_beat * 4, ticks_per_beat * 2, ticks_per_beat, ticks_per_beat // 2, ticks_per_beat // 4]
    remaining = duration
    chunks: list[int] = []
    for unit in units:
        while unit > 0 and remaining >= unit:
            chunks.append(unit)
            remaining -= unit
    if remaining:
        chunks.append(remaining)
    return chunks


def _rhythm_summary(stats: dict[str, int]) -> dict:
    return {
        "rhythm_mode": "groove_with_fill_tail",
        "groove_eighth_note_count": stats.get("groove_eighth_note_count", 0),
        "groove_sixteenth_note_count": stats.get("groove_sixteenth_note_count", 0),
        "fill_sixteenth_note_count": stats.get("fill_sixteenth_note_count", 0),
        "measures_with_fragmented_rests": stats.get("fragmented_rest_chunks", 0),
        "hihat_eighth_pulse_measure_count": stats.get("hihat_eighth_pulse_measure_count", 0),
        "hihat_quarter_pulse_measure_count": stats.get("hihat_quarter_pulse_measure_count", 0),
    }


def _build_chart_events(
    events: list[dict],
    *,
    ticks_per_beat: int,
    time_signature: str,
    chart_mode: str,
    max_events_per_measure: int,
) -> tuple[list[dict], dict]:
    beats, beat_type = _parse_time_signature(time_signature)
    measure_ticks = ticks_per_beat * beats * 4 // beat_type
    normalized = _normalize_events(events)
    original_counts = _drum_counts(normalized)
    original_measure_counts = _measure_counts(normalized, measure_ticks)
    dense_threshold = max_events_per_measure

    measure_count = max(1, (max((event["tick"] for event in normalized), default=0) // measure_ticks) + 1)

    if chart_mode == "readable_drum_chart_v3":
        chart_events, arranger_summary = _arrange_readable_chart_v3(
            normalized,
            measure_ticks,
            ticks_per_beat,
        )
        warnings = []
    elif chart_mode == "readable_drum_chart_v2":
        chart_events = _simplify_for_chart(normalized, measure_ticks, ticks_per_beat, max_events_per_measure)
        arranger_summary = {"repeat_measure_indices": []}
        warnings = []
    elif chart_mode != "simplified_chart_v1":
        chart_events = normalized
        arranger_summary = {}
        warnings = ["notation_chart_mode_full_transcription"]
    else:
        chart_events = _simplify_for_chart(normalized, measure_ticks, ticks_per_beat, max_events_per_measure)
        arranger_summary = {}
        warnings = []

    if chart_mode == "readable_drum_chart_v3":
        chart_events, cleanup_summary = _normalize_chart_rhythm(
            chart_events,
            measure_ticks,
            ticks_per_beat,
            arranger_summary.get("chart_measures", []),
        )
    else:
        cleanup_summary = {"off_grid_events_snapped": 0, "off_grid_events_dropped": 0}
    chart_events = _reindex_events(chart_events, ticks_per_beat)
    chart_counts = _drum_counts(chart_events)
    chart_onset_counts = _measure_onset_counts(chart_events, measure_ticks)
    dropped_counts = {
        drum: max(0, original_counts.get(drum, 0) - chart_counts.get(drum, 0))
        for drum in sorted(set(original_counts) | set(chart_counts))
    }
    dense_before = sum(1 for count in original_measure_counts.values() if count > dense_threshold)
    dense_after = sum(1 for count in chart_onset_counts.values() if count > dense_threshold)
    if dense_after:
        warnings.append("notation_chart_still_dense")
    if dropped_counts.get("tom", 0):
        warnings.append("notation_tom_reduced_for_readability")
    if dropped_counts.get("cymbal", 0):
        warnings.append("notation_cymbal_reduced_for_readability")
    warnings.extend(item for item in arranger_summary.get("warnings", []) if item not in warnings)
    repeat_measure_indices = arranger_summary.get("repeat_measure_indices", [])
    has_incomplete_core_grooves = arranger_summary.get("incomplete_core_groove_measure_count", 0) > 0
    has_missing_hihat_pulse = "chart_hihat_evidence_insufficient" in warnings
    if dense_after:
        readability_verdict = "still_too_dense"
    elif chart_mode == "readable_drum_chart_v3" and (has_incomplete_core_grooves or has_missing_hihat_pulse):
        readability_verdict = "needs_manual_arrangement"
    else:
        readability_verdict = "readable_chart_candidate"

    return chart_events, {
        "schema_version": "1.0",
        "mode": chart_mode,
        "readability_verdict": readability_verdict,
        "original_event_count": len(normalized),
        "chart_event_count": len(chart_events),
        "max_events_per_measure": max_events_per_measure,
        "max_visible_notes_per_measure": max(chart_onset_counts.values(), default=0),
        "measure_count": measure_count,
        "groove_measure_count": arranger_summary.get("groove_measure_count", 0),
        "repeat_measure_count": len(repeat_measure_indices),
        "repeat_measure_indices": repeat_measure_indices,
        "fill_measure_count": arranger_summary.get("fill_measure_count", 0),
        "accent_measure_count": arranger_summary.get("accent_measure_count", 0),
        "anchor_measure_count": arranger_summary.get("anchor_measure_count", 0),
        "literal_measure_count": arranger_summary.get("literal_measure_count", 0),
        "break_measure_count": arranger_summary.get("break_measure_count", 0),
        "stable_groove_section_count": arranger_summary.get("stable_groove_section_count", 0),
        "anchor_core_complete_count": arranger_summary.get("anchor_core_complete_count", 0),
        "anchor_hihat_pulse_count": arranger_summary.get("anchor_hihat_pulse_count", 0),
        "incomplete_anchor_count": arranger_summary.get("incomplete_anchor_count", 0),
        "repeat_with_complete_template_count": arranger_summary.get("repeat_with_complete_template_count", 0),
        "complete_core_groove_measure_count": arranger_summary.get("complete_core_groove_measure_count", 0),
        "incomplete_core_groove_measure_count": arranger_summary.get("incomplete_core_groove_measure_count", 0),
        "chart_hihat_evidence_measure_count": arranger_summary.get("chart_hihat_evidence_measure_count", 0),
        "chart_hihat_rendered_measure_count": arranger_summary.get("chart_hihat_rendered_measure_count", 0),
        "hihat_rendered_measure_count": arranger_summary.get("hihat_rendered_measure_count", 0),
        "measures_with_complete_core_groove": arranger_summary.get("complete_core_groove_measure_count", 0),
        "rhythm_mode": "groove_with_fill_tail",
        "groove_eighth_note_count": 0,
        "groove_sixteenth_note_count": 0,
        "fill_sixteenth_note_count": 0,
        "off_grid_events_snapped": cleanup_summary["off_grid_events_snapped"],
        "off_grid_events_dropped": cleanup_summary["off_grid_events_dropped"],
        "measures_with_fragmented_rests": 0,
        "hihat_eighth_pulse_measure_count": 0,
        "hihat_quarter_pulse_measure_count": 0,
        "chart_measures": arranger_summary.get("chart_measures", []),
        "preserved_counts": chart_counts,
        "dropped_counts": dropped_counts,
        "dense_measures_before": dense_before,
        "dense_measures_after": dense_after,
        "warnings": warnings,
    }


def _normalize_events(events: list[dict]) -> list[dict]:
    normalized = []
    for event in events:
        drum = canonical_drum_name(event.get("drum"))
        if drum is None:
            continue
        normalized.append(
            {
                "tick": int(event.get("tick", 0)),
                "drum": drum,
                "velocity": int(event.get("velocity", 80)),
            }
        )
    normalized.sort(key=lambda item: (item["tick"], item["drum"]))
    return normalized


def _arrange_readable_chart_v3(
    events: list[dict],
    measure_ticks: int,
    ticks_per_beat: int,
) -> tuple[list[dict], dict]:
    grouped: dict[int, list[dict]] = defaultdict(list)
    for event in events:
        grouped[event["tick"] // measure_ticks].append(event)

    measure_count = max(grouped.keys(), default=0) + 1
    measures: list[ChartMeasure] = []
    previous_tom_slots = 0
    warnings: list[str] = []
    complete_core_groove_measure_count = 0
    incomplete_core_groove_measure_count = 0
    chart_hihat_evidence_measure_count = 0
    hihat_rendered_measure_count = 0
    for measure_index in range(measure_count):
        local_events = [
            {**event, "local_tick": event["tick"] - measure_index * measure_ticks}
            for event in sorted(grouped.get(measure_index, []), key=lambda item: (item["tick"], item["drum"]))
        ]
        literal_events, render_kind, tom_slots = _arrange_v3_literal_measure(
            local_events,
            measure_index=measure_index,
            measure_ticks=measure_ticks,
            ticks_per_beat=ticks_per_beat,
            previous_tom_slots=previous_tom_slots,
        )
        measure = ChartMeasure(
            index=measure_index,
            render_kind=render_kind,
            events=tuple(literal_events),
            source_events=tuple(local_events),
        )
        measures.append(measure)
        if (
            any(
                event["drum"] == "tom" and event["local_tick"] >= measure_ticks - 2 * ticks_per_beat
                for event in measure.source_events
            )
            and render_kind != "fill"
        ):
            warnings.append("fill_evidence_insufficient")
        has_hihat_evidence = _has_hihat_evidence(measure.source_events)
        has_hihat = _has_hihat_event(measure.events)
        if has_hihat_evidence:
            chart_hihat_evidence_measure_count += 1
        if has_hihat:
            hihat_rendered_measure_count += 1
        if render_kind == "groove":
            if _has_complete_core_groove(measure.events):
                complete_core_groove_measure_count += 1
                if not _has_sufficient_hihat_evidence(measure.source_events, ticks_per_beat):
                    warnings.append("chart_hihat_evidence_insufficient")
            elif any(event["drum"] in {"kick", "snare"} for event in measure.source_events):
                incomplete_core_groove_measure_count += 1
                if not has_hihat_evidence:
                    warnings.append("chart_hihat_evidence_insufficient")
        previous_tom_slots = tom_slots

    chart_events = [
        {key: value for key, value in event.items() if key != "local_tick"}
        for measure in measures
        if measure.render_kind in {"groove", "fill", "break"}
        for event in measure.events
    ]
    fill_measure_count = sum(measure.render_kind == "fill" for measure in measures)
    break_measure_count = sum(measure.render_kind == "break" for measure in measures)
    literal_measure_count = sum(measure.render_kind in {"groove", "fill", "break"} for measure in measures)
    chart_measure_payloads = [_chart_measure_payload(measure, measure_ticks) for measure in measures]
    if fill_measure_count > max(4, measure_count // 4):
        warnings.append("notation_fill_density_needs_review")
    return sorted(chart_events, key=lambda item: (item["tick"], item["drum"])), {
        "groove_measure_count": sum(measure.render_kind == "groove" for measure in measures),
        "repeat_measure_indices": [],
        "fill_measure_count": fill_measure_count,
        "accent_measure_count": sum(
            any(event["drum"] == "cymbal" for event in measure.events) for measure in measures
        ),
        "anchor_measure_count": 0,
        "literal_measure_count": literal_measure_count,
        "break_measure_count": break_measure_count,
        "stable_groove_section_count": 0,
        "anchor_core_complete_count": 0,
        "anchor_hihat_pulse_count": 0,
        "incomplete_anchor_count": 0,
        "repeat_with_complete_template_count": 0,
        "complete_core_groove_measure_count": complete_core_groove_measure_count,
        "incomplete_core_groove_measure_count": incomplete_core_groove_measure_count,
        "chart_hihat_evidence_measure_count": chart_hihat_evidence_measure_count,
        "chart_hihat_rendered_measure_count": hihat_rendered_measure_count,
        "hihat_rendered_measure_count": hihat_rendered_measure_count,
        "chart_measures": chart_measure_payloads,
        "warnings": warnings,
    }


def _arrange_v3_literal_measure(
    events: list[dict],
    *,
    measure_index: int,
    measure_ticks: int,
    ticks_per_beat: int,
    previous_tom_slots: int,
) -> tuple[list[dict], str, int]:
    if not events:
        return [], "rest", 0
    hats = [event for event in events if event["drum"] == "hi_hat"]
    kicks = [event for event in events if event["drum"] == "kick"]
    snares = [event for event in events if event["drum"] == "snare"]
    cymbals = [event for event in events if event["drum"] == "cymbal"]
    toms = [event for event in events if event["drum"] == "tom"]
    tom_slots = len(_quantized_slots(toms, ticks_per_beat))

    selected: dict[tuple[int, str], dict] = {}
    for event in _v3_hat_pulse(hats, measure_index, measure_ticks, ticks_per_beat):
        selected[(event["tick"], event["drum"])] = event
    for event in _readable_backbeat_snares(snares, measure_index, measure_ticks, ticks_per_beat):
        selected[(event["tick"], event["drum"])] = event
    for event in _readable_kicks(kicks, measure_index, measure_ticks, ticks_per_beat):
        selected[(event["tick"], event["drum"])] = event

    fill_toms = _v3_tom_fill(
        toms,
        measure_index,
        measure_ticks,
        ticks_per_beat,
        previous_tom_slots=previous_tom_slots,
    )
    for event in fill_toms:
        selected[(event["tick"], event["drum"])] = event

    if not selected and cymbals:
        accent = _readable_cymbal_accent(cymbals, measure_index, measure_ticks, ticks_per_beat, keep=True)
        return ([accent] if accent else []), "break", tom_slots
    return (
        sorted(selected.values(), key=lambda item: (item["tick"], item["drum"])),
        "fill" if fill_toms else "groove",
        tom_slots,
    )


def _v3_hat_pulse(events: list[dict], measure_index: int, measure_ticks: int, ticks_per_beat: int) -> list[dict]:
    slots = _quantized_slots(events, ticks_per_beat)
    if not slots:
        return []
    grid = list(range(8)) if len(slots) >= 5 else [0, 2, 4, 6]
    template_event = max(events, key=lambda event: event.get("velocity", 0))
    result = []
    for slot in grid:
        local_tick = slot * ticks_per_beat // 2
        event = _nearest_local_event(events, local_tick, window=max(1, ticks_per_beat // 3))
        # Sparse detections still establish a playable pulse. The source event
        # determines the drum class; the chart grid supplies readable timing.
        source_event = event or template_event
        result.append(_canonical_event(source_event, measure_index, measure_ticks, local_tick, source_event["drum"]))
    return _unique_events(result)


def _v3_tom_fill(
    events: list[dict],
    measure_index: int,
    measure_ticks: int,
    ticks_per_beat: int,
    *,
    previous_tom_slots: int,
) -> list[dict]:
    fill_start = max(0, measure_ticks - 2 * ticks_per_beat)
    fill_events = [event for event in events if event["local_tick"] >= fill_start]
    pre_fill_slots = _quantized_slots(
        [event for event in events if event["local_tick"] < fill_start],
        ticks_per_beat,
    )
    sixteenth = max(1, ticks_per_beat // 4)
    slots = sorted({round(event["local_tick"] / sixteenth) for event in fill_events})
    runs: list[list[int]] = []
    for slot in slots:
        if runs and slot == runs[-1][-1] + 1:
            runs[-1].append(slot)
        else:
            runs.append([slot])
    credible_run = next((run for run in reversed(runs) if len(run) >= 3), [])
    if not credible_run or previous_tom_slots > 1 or len(pre_fill_slots) > 1:
        return []
    result = []
    for slot in credible_run[-4:]:
        local_tick = slot * sixteenth
        event = _nearest_local_event(fill_events, local_tick, window=max(1, sixteenth // 2))
        if event is not None:
            result.append(_canonical_event(event, measure_index, measure_ticks, local_tick, "tom"))
    return _unique_events(result)[:4]


def _quantized_slots(events: list[dict], ticks_per_beat: int) -> list[int]:
    if ticks_per_beat <= 0:
        return []
    return sorted({max(0, min(7, round(event["local_tick"] / (ticks_per_beat / 2)))) for event in events})


def _has_core_groove(events: tuple[dict, ...] | list[dict]) -> bool:
    drums = {event["drum"] for event in events}
    return "kick" in drums and "snare" in drums


def _has_complete_core_groove(events: tuple[dict, ...] | list[dict]) -> bool:
    drums = {event["drum"] for event in events}
    return {"kick", "snare", "hi_hat"}.issubset(drums)


def _has_hihat_event(events: tuple[dict, ...] | list[dict]) -> bool:
    return any(event["drum"] == "hi_hat" for event in events)


def _has_hihat_evidence(events: tuple[dict, ...]) -> bool:
    return any(event["drum"] == "hi_hat" for event in events)


def _has_sufficient_hihat_evidence(events: tuple[dict, ...], ticks_per_beat: int) -> bool:
    hats = [event for event in events if event["drum"] == "hi_hat"]
    return len(_quantized_slots(hats, ticks_per_beat)) >= 3


def _chart_measure_payload(
    measure: ChartMeasure,
    measure_ticks: int,
) -> dict:
    return {
        "measure_index": measure.index,
        "source_measure_indices": [measure.index],
        "render_kind": measure.render_kind,
        "event_count": len(measure.events),
        "visible_onset_count": len({event["tick"] - measure.index * measure_ticks for event in measure.events}),
    }


def _readable_backbeat_snares(events: list[dict], measure_index: int, measure_ticks: int, ticks_per_beat: int) -> list[dict]:
    result: list[dict] = []
    for local_tick in (ticks_per_beat, 3 * ticks_per_beat):
        event = _nearest_local_event(events, local_tick, window=max(1, ticks_per_beat // 2))
        if event is not None:
            result.append(_canonical_event(event, measure_index, measure_ticks, local_tick, "snare"))
    # The readable chart prefers conventional backbeats, but a model can return
    # a valid snare onset outside that narrow window. Preserve up to two real
    # source onsets rather than silently making a snare-less chart measure.
    # This only quantizes an existing snare; it never invents or remaps a drum.
    selected_slots = {event["local_tick"] for event in result}
    for event in sorted(events, key=lambda item: (_backbeat_distance(item["local_tick"], ticks_per_beat), -item.get("velocity", 0))):
        if len(result) >= 2:
            break
        local_tick = _nearest_eighth_tick(event["local_tick"], ticks_per_beat)
        if local_tick in selected_slots:
            continue
        result.append(_canonical_event(event, measure_index, measure_ticks, local_tick, "snare"))
        selected_slots.add(local_tick)
    return sorted(result, key=lambda item: item["tick"])


def _readable_kicks(events: list[dict], measure_index: int, measure_ticks: int, ticks_per_beat: int) -> list[dict]:
    if not events:
        return []
    grid = [index * ticks_per_beat // 2 for index in range(8)]
    candidates = []
    used_source_events: set[int] = set()
    for local_tick in grid:
        event = _nearest_local_event(events, local_tick, window=max(1, ticks_per_beat // 3))
        if event is not None and id(event) not in used_source_events:
            candidates.append(_canonical_event(event, measure_index, measure_ticks, local_tick, "kick"))
            used_source_events.add(id(event))
    candidates = _unique_events(candidates)
    selected_slots = {event["local_tick"] for event in candidates}
    # Keep the readable three-to-four kick limit, but do not drop all source
    # evidence merely because it landed outside the tight canonical window.
    for event in sorted(events, key=lambda item: (-item.get("velocity", 0), item["local_tick"])):
        if len(candidates) >= 4:
            break
        local_tick = _nearest_eighth_tick(event["local_tick"], ticks_per_beat)
        if local_tick in selected_slots:
            continue
        candidates.append(_canonical_event(event, measure_index, measure_ticks, local_tick, "kick"))
        selected_slots.add(local_tick)
    return sorted(candidates, key=lambda item: (_kick_priority(item, ticks_per_beat), item["tick"]))[:4]


def _kick_priority(event: dict, ticks_per_beat: int) -> tuple[int, int]:
    local_tick = event["local_tick"]
    downbeat_bonus = 0 if local_tick == 0 else 1
    onbeat_bonus = 0 if local_tick % ticks_per_beat == 0 else 1
    return (downbeat_bonus, onbeat_bonus)


def _nearest_eighth_tick(local_tick: int, ticks_per_beat: int) -> int:
    subdivision = max(1, ticks_per_beat // 2)
    return max(0, min(7 * subdivision, round(local_tick / subdivision) * subdivision))


def _backbeat_distance(local_tick: int, ticks_per_beat: int) -> int:
    return min(abs(local_tick - ticks_per_beat), abs(local_tick - 3 * ticks_per_beat))


def _readable_cymbal_accent(
    events: list[dict],
    measure_index: int,
    measure_ticks: int,
    ticks_per_beat: int,
    *,
    keep: bool,
) -> dict | None:
    if not keep:
        return None
    event = _nearest_local_event(events, 0, window=max(1, ticks_per_beat // 3))
    if event is None:
        return None
    return _canonical_event(event, measure_index, measure_ticks, 0, "cymbal")


def _nearest_local_event(events: list[dict], local_tick: int, *, window: int) -> dict | None:
    candidates = [event for event in events if abs(event["local_tick"] - local_tick) <= window]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (abs(item["local_tick"] - local_tick), -item.get("velocity", 0)))[0]


def _canonical_event(event: dict, measure_index: int, measure_ticks: int, local_tick: int, drum: str) -> dict:
    tick = measure_index * measure_ticks + local_tick
    return {
        "tick": tick,
        "local_tick": local_tick,
        "drum": drum,
        "velocity": event.get("velocity", 80),
    }


def _simplify_for_chart(
    events: list[dict],
    measure_ticks: int,
    ticks_per_beat: int,
    max_events_per_measure: int,
) -> list[dict]:
    grouped: dict[int, list[dict]] = defaultdict(list)
    for event in events:
        grouped[event["tick"] // measure_ticks].append(event)

    chart_events: list[dict] = []
    for measure_index in sorted(grouped):
        measure_events = sorted(grouped[measure_index], key=lambda item: (item["tick"], item["drum"]))
        local_events = [
            {
                **event,
                "local_tick": event["tick"] - measure_index * measure_ticks,
            }
            for event in measure_events
        ]
        selected = _select_core_chart_events(local_events, measure_ticks, ticks_per_beat)
        if len(selected) > max_events_per_measure:
            selected = _trim_measure_events(selected, max_events_per_measure, ticks_per_beat)
        chart_events.extend({key: value for key, value in event.items() if key != "local_tick"} for event in selected)
    return sorted(chart_events, key=lambda item: (item["tick"], item["drum"]))


def _select_core_chart_events(events: list[dict], measure_ticks: int, ticks_per_beat: int) -> list[dict]:
    selected: dict[tuple[int, str], dict] = {}
    hats = [event for event in events if event["drum"] == "hi_hat"]
    cymbals = [event for event in events if event["drum"] == "cymbal"]
    toms = [event for event in events if event["drum"] == "tom"]

    for event in events:
        if event["drum"] in {"kick", "snare"}:
            selected[(event["tick"], event["drum"])] = event

    for event in _pulse_events(hats, ticks_per_beat, max_per_measure=8):
        selected[(event["tick"], event["drum"])] = event

    opening_cymbal = _first_near_tick(cymbals, target_tick=0, window=max(1, ticks_per_beat // 4))
    if opening_cymbal is not None:
        selected[(opening_cymbal["tick"], opening_cymbal["drum"])] = opening_cymbal

    for event in _fill_tom_events(toms, measure_ticks, ticks_per_beat):
        selected[(event["tick"], event["drum"])] = event

    return sorted(selected.values(), key=lambda item: (item["tick"], item["drum"]))


def _pulse_events(events: list[dict], ticks_per_beat: int, *, max_per_measure: int) -> list[dict]:
    if not events:
        return []
    subdivision = max(1, ticks_per_beat // 2)
    buckets: dict[int, dict] = {}
    for event in events:
        bucket = round(event["local_tick"] / subdivision)
        current = buckets.get(bucket)
        if current is None or abs(event["local_tick"] - bucket * subdivision) < abs(current["local_tick"] - bucket * subdivision):
            buckets[bucket] = event
    return [buckets[key] for key in sorted(buckets)[:max_per_measure]]


def _first_near_tick(events: list[dict], *, target_tick: int, window: int) -> dict | None:
    candidates = [event for event in events if abs(event["local_tick"] - target_tick) <= window]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (abs(item["local_tick"] - target_tick), item["tick"]))[0]


def _fill_tom_events(events: list[dict], measure_ticks: int, ticks_per_beat: int) -> list[dict]:
    if len(events) < 2:
        return []
    fill_start = max(0, measure_ticks - 2 * ticks_per_beat)
    fill_events = [event for event in events if event["local_tick"] >= fill_start]
    if len(fill_events) < 2:
        return []
    return fill_events[:4]


def _trim_measure_events(events: list[dict], max_events: int, ticks_per_beat: int) -> list[dict]:
    def aligned(events_for_drum: list[dict], limit: int) -> list[dict]:
        return sorted(events_for_drum, key=lambda item: (_beat_alignment(item, ticks_per_beat), item["tick"]))[:limit]

    kicks = aligned([event for event in events if event["drum"] == "kick"], 4)
    snares = aligned([event for event in events if event["drum"] == "snare"], 4)
    hats = aligned([event for event in events if event["drum"] == "hi_hat"], 4)
    cymbals = aligned([event for event in events if event["drum"] == "cymbal"], 1)
    toms = aligned([event for event in events if event["drum"] == "tom"], 2)
    kept = _unique_events([*kicks, *snares, *hats, *cymbals, *toms])
    if len(kept) <= max_events:
        return sorted(kept, key=lambda item: (item["tick"], item["drum"]))

    def priority(event: dict) -> tuple[int, int, int]:
        drum_priority = {"snare": 0, "kick": 0, "hi_hat": 1, "cymbal": 2, "tom": 3}.get(
            event["drum"],
            4,
        )
        return (drum_priority, _beat_alignment(event, ticks_per_beat), event["tick"])

    return sorted(sorted(kept, key=priority)[:max_events], key=lambda item: (item["tick"], item["drum"]))


def _beat_alignment(event: dict, ticks_per_beat: int) -> int:
    if ticks_per_beat <= 0:
        return 0
    remainder = event["local_tick"] % ticks_per_beat
    return min(remainder, ticks_per_beat - remainder)


def _unique_events(events: list[dict]) -> list[dict]:
    result: dict[tuple[int, str], dict] = {}
    for event in events:
        result[(event["tick"], event["drum"])] = event
    return list(result.values())


def _write_chart_events(
    path: Path,
    *,
    source_payload: dict,
    chart_events: list[dict],
    chart_summary: dict,
    tempo_bpm: float,
    tempo_source: str,
) -> None:
    payload = {
        "schema_version": "1.0",
        "drum_taxonomy": DRUM_TAXONOMY_ID,
        "source": "notation_simplifier",
        "ticks_per_beat": source_payload.get("ticks_per_beat", 480),
        "estimated_bpm": tempo_bpm,
        "tempo_bpm": tempo_bpm,
        "tempo_source": tempo_source,
        "time_signature": source_payload.get("time_signature", "4/4"),
        "event_count": len(chart_events),
        "chart_summary": chart_summary,
        "measures": chart_summary.get("chart_measures", []),
        "events": chart_events,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _drum_counts(events: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        counts[event["drum"]] += 1
    return dict(sorted(counts.items()))


def _measure_counts(events: list[dict], measure_ticks: int) -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    for event in events:
        counts[event["tick"] // measure_ticks] += 1
    return dict(counts)


def _measure_onset_counts(events: list[dict], measure_ticks: int) -> dict[int, int]:
    onsets: dict[int, set[int]] = defaultdict(set)
    for event in events:
        measure_index = event["tick"] // measure_ticks
        onsets[measure_index].add(event["tick"] % measure_ticks)
    return {measure_index: len(ticks) for measure_index, ticks in onsets.items()}


def _reindex_events(events: list[dict], ticks_per_beat: int) -> list[dict]:
    indexed = []
    for index, event in enumerate(sorted(events, key=lambda item: (item["tick"], item["drum"]))):
        indexed.append(
            {
                "index": index,
                "tick": event["tick"],
                "beat": round(event["tick"] / ticks_per_beat, 4),
                "drum": event["drum"],
                "midi_note": _midi_note_for_drum(event["drum"]),
                "velocity": event.get("velocity", 80),
            }
        )
    return indexed


def _normalize_chart_rhythm(
    events: list[dict],
    measure_ticks: int,
    ticks_per_beat: int,
    chart_measures: list[dict],
) -> tuple[list[dict], dict[str, int]]:
    """Snap chart notation to a readable grid without changing processed MIDI."""
    measure_kinds = {int(item.get("measure_index", -1)): str(item.get("render_kind", "groove")) for item in chart_measures}
    selected: dict[tuple[int, str], tuple[dict, int]] = {}
    snapped = 0
    dropped = 0
    for event in events:
        measure_index = int(event["tick"]) // measure_ticks
        local_tick = int(event["tick"]) % measure_ticks
        render_kind = measure_kinds.get(measure_index, "groove")
        fill_tail = render_kind == "fill" and local_tick >= measure_ticks - 2 * ticks_per_beat
        unit = max(1, ticks_per_beat // 4) if fill_tail and event["drum"] in {"tom", "snare"} else max(1, ticks_per_beat // 2)
        snapped_local_tick = max(0, min(measure_ticks - unit, round(local_tick / unit) * unit))
        distance = abs(local_tick - snapped_local_tick)
        if distance:
            snapped += 1
        normalized = {**event, "tick": measure_index * measure_ticks + snapped_local_tick}
        key = (normalized["tick"], normalized["drum"])
        previous = selected.get(key)
        if previous is None:
            selected[key] = (normalized, distance)
        elif (normalized.get("velocity", 0), -distance) > (previous[0].get("velocity", 0), -previous[1]):
            selected[key] = (normalized, distance)
            dropped += 1
        else:
            dropped += 1
    return (
        [item for item, _distance in sorted(selected.values(), key=lambda pair: (pair[0]["tick"], pair[0]["drum"]))],
        {"off_grid_events_snapped": snapped, "off_grid_events_dropped": dropped},
    )


def _fragmented_rest_measure_count(score: ET.Element, measure_kinds: dict[int, str]) -> int:
    count = 0
    for measure_index, measure in enumerate(score.findall("./part/measure")):
        if measure_kinds.get(measure_index, "groove") == "fill":
            continue
        if any(note.find("rest") is not None and note.findtext("type") == "16th" for note in measure.findall("note")):
            count += 1
    return count


def _midi_note_for_drum(drum: str) -> int:
    return DRUM_DISPLAYS.get(drum, DRUM_DISPLAYS["snare"]).midi_note


def _events_for_voice(grouped: dict[tuple[int, int], list[dict]], measure_index: int, voice: str) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = defaultdict(list)
    for idx, local_tick in grouped:
        if idx != measure_index:
            continue
        for event in grouped[(idx, local_tick)]:
            if DRUM_DISPLAYS[event["drum"]].voice == voice:
                result[local_tick].append(event)
    return dict(result)


def _beam_map(events_by_tick: dict[int, list[dict]], ticks_per_beat: int) -> dict[int, str]:
    ticks_by_beat: dict[int, list[int]] = defaultdict(list)
    for local_tick in events_by_tick:
        ticks_by_beat[local_tick // ticks_per_beat].append(local_tick)

    result: dict[int, str] = {}
    for ticks in ticks_by_beat.values():
        ordered = sorted(ticks)
        if len(ordered) < 2:
            continue
        for index, tick in enumerate(ordered):
            if index == 0:
                result[tick] = "begin"
            elif index == len(ordered) - 1:
                result[tick] = "end"
            else:
                result[tick] = "continue"
    return result


def _readability_summary(
    events: list[dict],
    *,
    measure_count: int,
    measure_event_counts: dict[int, int],
    layout_profile: str,
) -> dict:
    hand_count = sum(1 for event in events if DRUM_DISPLAYS[event["drum"]].voice == HAND_VOICE)
    foot_count = sum(1 for event in events if DRUM_DISPLAYS[event["drum"]].voice == FOOT_VOICE)
    generic_tom_count = sum(1 for event in events if event["drum"] == "tom")
    dense_measure_threshold = 24
    dense_measure_count = sum(1 for count in measure_event_counts.values() if count > dense_measure_threshold)
    warnings = []
    if dense_measure_count:
        warnings.append("notation_dense_full_mix_likely")
    if generic_tom_count:
        warnings.append("generic_tom_position_used")
    return {
        "schema_version": "1.0",
        "layout_profile": layout_profile,
        "voice_count": int(bool(hand_count)) + int(bool(foot_count)),
        "has_hand_voice": bool(hand_count),
        "has_foot_voice": bool(foot_count),
        "hand_event_count": hand_count,
        "foot_event_count": foot_count,
        "generic_tom_count": generic_tom_count,
        "measure_count": measure_count,
        "dense_measure_count": dense_measure_count,
        "dense_measure_threshold": dense_measure_threshold,
        "warnings": warnings,
    }
