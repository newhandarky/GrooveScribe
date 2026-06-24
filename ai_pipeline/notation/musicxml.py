from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from ai_pipeline.notation.errors import MusicXmlInvalidError, NotationGenerationFailedError
from ai_pipeline.notation.types import MusicXmlResult, NotationConfig

DRUM_POSITIONS = {
    "kick": ("F", 4, "normal"),
    "snare": ("C", 5, "normal"),
    "closed_hat": ("G", 5, "x"),
    "pedal_hat": ("G", 5, "x"),
    "open_hat": ("G", 5, "x"),
    "tom": ("D", 5, "normal"),
    "cymbal": ("A", 5, "x"),
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
        root = self._build_score(events, ticks_per_beat, estimated_bpm, time_signature)
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(musicxml_path, encoding="utf-8", xml_declaration=True)
        self._validate_musicxml(musicxml_path)

        measure_count = len(root.findall("./part/measure"))
        return MusicXmlResult(
            musicxml_path=musicxml_path,
            event_count=len(events),
            measure_count=measure_count,
            title=self.config.title,
        )

    def _build_score(self, events, ticks_per_beat: int, estimated_bpm: float, time_signature: str) -> ET.Element:
        beats, beat_type = _parse_time_signature(time_signature)
        measure_ticks = ticks_per_beat * beats * 4 // beat_type
        note_duration = self.config.note_duration_ticks or max(1, ticks_per_beat // 4)
        divisions = self.config.divisions_per_quarter or ticks_per_beat

        normalized_events = []
        for event in events:
            drum = str(event.get("drum", "snare"))
            if drum not in DRUM_POSITIONS:
                drum = "snare"
            normalized_events.append(
                {
                    "tick": int(event.get("tick", 0)),
                    "drum": drum,
                    "velocity": int(event.get("velocity", 80)),
                }
            )
        normalized_events.sort(key=lambda item: (item["tick"], item["drum"]))

        last_tick = max(item["tick"] for item in normalized_events) + note_duration
        measure_count = max(1, math.ceil(last_tick / measure_ticks))
        grouped = defaultdict(list)
        for event in normalized_events:
            measure_index = event["tick"] // measure_ticks
            local_tick = event["tick"] % measure_ticks
            grouped[(measure_index, local_tick)].append(event)

        score = ET.Element("score-partwise", version="3.1")
        work = ET.SubElement(score, "work")
        ET.SubElement(work, "work-title").text = self.config.title
        identification = ET.SubElement(score, "identification")
        creator = ET.SubElement(identification, "creator", type="composer")
        creator.text = self.config.composer
        part_list = ET.SubElement(score, "part-list")
        score_part = ET.SubElement(part_list, "score-part", id="P1")
        ET.SubElement(score_part, "part-name").text = self.config.part_name
        score_instrument = ET.SubElement(score_part, "score-instrument", id="P1-I1")
        ET.SubElement(score_instrument, "instrument-name").text = "Drum Kit"
        midi_instrument = ET.SubElement(score_part, "midi-instrument", id="P1-I1")
        ET.SubElement(midi_instrument, "midi-channel").text = "10"
        ET.SubElement(midi_instrument, "midi-program").text = "1"

        part = ET.SubElement(score, "part", id="P1")
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
                direction = ET.SubElement(measure, "direction", placement="above")
                direction_type = ET.SubElement(direction, "direction-type")
                metronome = ET.SubElement(direction_type, "metronome")
                ET.SubElement(metronome, "beat-unit").text = "quarter"
                ET.SubElement(metronome, "per-minute").text = str(round(estimated_bpm))
                sound = ET.SubElement(direction, "sound")
                sound.set("tempo", str(round(estimated_bpm, 2)))

            cursor = 0
            local_ticks = sorted(local_tick for idx, local_tick in grouped if idx == measure_index)
            for local_tick in local_ticks:
                if local_tick > cursor:
                    self._append_rest(measure, local_tick - cursor)
                events_at_tick = grouped[(measure_index, local_tick)]
                for event_index, event in enumerate(events_at_tick):
                    self._append_drum_note(measure, event["drum"], note_duration, chord=event_index > 0)
                cursor = max(cursor, local_tick + note_duration)
            if cursor < measure_ticks:
                self._append_rest(measure, measure_ticks - cursor)

        return score

    def _append_rest(self, measure: ET.Element, duration: int) -> None:
        if duration <= 0:
            return
        note = ET.SubElement(measure, "note")
        ET.SubElement(note, "rest")
        ET.SubElement(note, "duration").text = str(duration)
        ET.SubElement(note, "voice").text = "1"
        ET.SubElement(note, "type").text = _duration_type(duration)

    def _append_drum_note(self, measure: ET.Element, drum: str, duration: int, chord: bool = False) -> None:
        display_step, display_octave, notehead = DRUM_POSITIONS[drum]
        note = ET.SubElement(measure, "note")
        if chord:
            ET.SubElement(note, "chord")
        unpitched = ET.SubElement(note, "unpitched")
        ET.SubElement(unpitched, "display-step").text = display_step
        ET.SubElement(unpitched, "display-octave").text = str(display_octave)
        ET.SubElement(note, "duration").text = str(duration)
        ET.SubElement(note, "instrument", id="P1-I1")
        ET.SubElement(note, "voice").text = "1"
        ET.SubElement(note, "type").text = _duration_type(duration)
        ET.SubElement(note, "stem").text = "up"
        if notehead != "normal":
            ET.SubElement(note, "notehead").text = notehead

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


def _duration_type(duration: int) -> str:
    if duration >= 1920:
        return "whole"
    if duration >= 960:
        return "half"
    if duration >= 480:
        return "quarter"
    if duration >= 240:
        return "eighth"
    return "16th"
