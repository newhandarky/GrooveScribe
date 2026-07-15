import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from ai_pipeline.local_runner import LocalPipelineConfig, LocalPipelineRunner
from ai_pipeline.notation.musicxml import MusicXmlGenerator
from ai_pipeline.notation.pdf import MuseScorePdfExporter
from ai_pipeline.notation.types import NotationConfig
from ai_pipeline.notation.types import MuseScoreVisualQaResult
from ai_pipeline.notation.validation import validate_musicxml_artifact, validate_pdf_artifact


def _write_events(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "ticks_per_beat": 480,
        "estimated_bpm": 120.0,
        "time_signature": "4/4",
        "event_count": 3,
        "events": [
            {"index": 0, "tick": 0, "beat": 0.0, "drum": "kick", "midi_note": 36, "velocity": 100},
            {"index": 1, "tick": 120, "beat": 0.25, "drum": "snare", "midi_note": 38, "velocity": 90},
            {"index": 2, "tick": 240, "beat": 0.5, "drum": "closed_hat", "midi_note": 42, "velocity": 80},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_layered_events(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "ticks_per_beat": 480,
        "estimated_bpm": 120.0,
        "time_signature": "4/4",
        "event_count": 7,
        "events": [
            {"index": 0, "tick": 0, "beat": 0.0, "drum": "kick", "midi_note": 36, "velocity": 100},
            {"index": 1, "tick": 0, "beat": 0.0, "drum": "closed_hat", "midi_note": 42, "velocity": 80},
            {"index": 2, "tick": 240, "beat": 0.5, "drum": "closed_hat", "midi_note": 42, "velocity": 80},
            {"index": 3, "tick": 480, "beat": 1.0, "drum": "snare", "midi_note": 38, "velocity": 95},
            {"index": 4, "tick": 480, "beat": 1.0, "drum": "kick", "midi_note": 36, "velocity": 100},
            {"index": 5, "tick": 1440, "beat": 3.0, "drum": "tom", "midi_note": 45, "velocity": 90},
            {"index": 6, "tick": 1560, "beat": 3.25, "drum": "tom", "midi_note": 45, "velocity": 90},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_standard_drum_mapping_events(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    events = [
        (0, "kick", 36),
        (240, "closed_hat", 42),
        (480, "snare", 38),
        (720, "open_hat", 46),
        (960, "tom", 45),
        (1440, "cymbal", 49),
    ]
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "ticks_per_beat": 480,
                "estimated_bpm": 120.0,
                "time_signature": "4/4",
                "event_count": len(events),
                "events": [
                    {
                        "index": index,
                        "tick": tick,
                        "beat": tick / 480,
                        "drum": drum,
                        "midi_note": midi_note,
                        "velocity": 100,
                    }
                    for index, (tick, drum, midi_note) in enumerate(events)
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_dense_chart_events(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    events = []
    index = 0
    for measure in range(2):
        base = measure * 1920
        for offset in range(0, 1920, 120):
            for drum, note in (
                ("closed_hat", 42),
                ("kick", 36),
                ("snare", 38),
                ("tom", 45),
                ("cymbal", 49),
            ):
                events.append(
                    {
                        "index": index,
                        "tick": base + offset,
                        "beat": (base + offset) / 480,
                        "drum": drum,
                        "midi_note": note,
                        "velocity": 100,
                    }
                )
                index += 1
    payload = {
        "schema_version": "1.0",
        "ticks_per_beat": 480,
        "estimated_bpm": 120.0,
        "time_signature": "4/4",
        "event_count": len(events),
        "events": events,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_readable_v2_events(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    events = []
    index = 0

    def add(measure: int, local_tick: int, drum: str, note: int) -> None:
        nonlocal index
        tick = measure * 1920 + local_tick
        events.append(
            {
                "index": index,
                "tick": tick,
                "beat": tick / 480,
                "drum": drum,
                "midi_note": note,
                "velocity": 100,
            }
        )
        index += 1

    for measure in (0, 1):
        for local_tick in range(0, 1920, 240):
            add(measure, local_tick, "closed_hat", 42)
        add(measure, 0, "kick", 36)
        add(measure, 960, "kick", 36)
        add(measure, 480, "snare", 38)
        add(measure, 1440, "snare", 38)
        add(measure, 120, "snare", 38)
        add(measure, 600, "snare", 38)
        add(measure, 720, "tom", 45)
        add(measure, 840, "tom", 45)
    for local_tick in (0, 240, 480, 720):
        add(2, local_tick, "closed_hat", 42)
    add(2, 0, "kick", 36)
    add(2, 480, "snare", 38)
    add(2, 960, "snare", 38)
    add(2, 1080, "tom", 45)
    add(2, 1320, "tom", 45)
    add(2, 1560, "tom", 45)

    payload = {
        "schema_version": "1.0",
        "ticks_per_beat": 480,
        "estimated_bpm": 120.0,
        "time_signature": "4/4",
        "event_count": len(events),
        "events": events,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_readable_v3_section_events(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    events = []
    index = 0

    def add(measure: int, local_tick: int, drum: str, note: int) -> None:
        nonlocal index
        tick = measure * 1920 + local_tick
        events.append(
            {
                "index": index,
                "tick": tick,
                "beat": tick / 480,
                "drum": drum,
                "midi_note": note,
                "velocity": 100,
            }
        )
        index += 1

    for measure in range(8):
        for local_tick in range(0, 1920, 240):
            add(measure, local_tick, "closed_hat", 42)
        add(measure, 0, "kick", 36)
        add(measure, 960 if measure == 3 else 720, "kick", 36)
        add(measure, 480, "snare", 38)
        add(measure, 1440, "snare", 38)
        add(measure, 120, "snare", 38)  # ghost note; must not render.

    # A real fill candidate: three tom onsets at the end after a non-tom groove.
    for local_tick in (1320, 1440, 1560):
        add(8, local_tick, "tom", 45)
    add(8, 0, "kick", 36)
    add(8, 480, "snare", 38)

    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "ticks_per_beat": 480,
                "estimated_bpm": 120.0,
                "time_signature": "4/4",
                "event_count": len(events),
                "events": events,
            }
        ),
        encoding="utf-8",
    )


def test_musicxml_generator_writes_parseable_score(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_events(events_path)

    result = MusicXmlGenerator(NotationConfig(chart_mode="readable_drum_chart_v2")).generate(events_path, tmp_path / "notation")

    assert result.musicxml_path.exists()
    root = ET.parse(result.musicxml_path).getroot()
    assert root.tag == "score-partwise"
    assert root.find("./part/measure/note") is not None
    assert result.event_count == 3


def test_musicxml_generator_uses_standard_drum_two_voice_layout(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_layered_events(events_path)

    result = MusicXmlGenerator(NotationConfig(chart_mode="readable_drum_chart_v2")).generate(events_path, tmp_path / "notation")

    root = ET.parse(result.musicxml_path).getroot()
    measure = root.find("./part/measure")
    assert measure is not None
    assert measure.find("backup/duration").text == "1920"
    voices = [note.findtext("voice") for note in measure.findall("note")]
    assert "1" in voices
    assert "2" in voices
    assert result.readability_summary["layout_profile"] == "standard_drum_v1"
    assert result.readability_summary["has_hand_voice"] is True
    assert result.readability_summary["has_foot_voice"] is True
    assert result.readability_summary["generic_tom_count"] == 2
    assert "generic_tom_position_used" in result.readability_summary["warnings"]

    notes = measure.findall("note")
    hat_notes = [
        note
        for note in notes
        if note.findtext("unpitched/display-step") == "G" and note.findtext("notehead") == "x"
    ]
    kick_notes = [
        note
        for note in notes
        if note.findtext("unpitched/display-step") == "F" and note.findtext("voice") == "2"
    ]
    assert hat_notes
    assert kick_notes
    assert all(note.findtext("stem") == "up" for note in hat_notes)
    assert all(note.findtext("stem") == "down" for note in kick_notes)
    assert any(note.find("beam") is not None for note in hat_notes)


def test_musicxml_generator_declares_standard_drum_instruments_per_note(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_standard_drum_mapping_events(events_path)

    result = MusicXmlGenerator(NotationConfig(chart_mode="full_transcription")).generate(events_path, tmp_path / "notation")
    root = ET.parse(result.musicxml_path).getroot()
    score_part = root.find("./part-list/score-part")
    assert score_part is not None

    expected = {
        "P1-I36": ("Bass Drum 1", "36"),
        "P1-I38": ("Acoustic Snare", "38"),
        "P1-I42": ("Closed Hi-Hat", "42"),
        "P1-I44": ("Pedal Hi-Hat", "44"),
        "P1-I46": ("Open Hi-Hat", "46"),
        "P1-I45": ("Low Tom", "45"),
        "P1-I49": ("Crash Cymbal 1", "49"),
    }
    score_instruments = {
        item.get("id"): item.findtext("instrument-name")
        for item in score_part.findall("score-instrument")
    }
    midi_instruments = {
        item.get("id"): (item.findtext("midi-channel"), item.findtext("midi-unpitched"))
        for item in score_part.findall("midi-instrument")
    }
    assert score_instruments == {instrument_id: values[0] for instrument_id, values in expected.items()}
    assert midi_instruments == {instrument_id: ("10", values[1]) for instrument_id, values in expected.items()}
    assert root.findtext("./part/measure/attributes/staff-details/staff-lines") == "5"

    notes_by_instrument = {
        note.find("instrument").get("id"): note
        for note in root.findall("./part/measure/note")
        if note.find("instrument") is not None
    }
    assert set(notes_by_instrument) == {"P1-I36", "P1-I38", "P1-I42", "P1-I46", "P1-I45", "P1-I49"}
    positions = {
        instrument_id: (
            note.findtext("unpitched/display-step"),
            note.findtext("unpitched/display-octave"),
            note.findtext("voice"),
            note.findtext("stem"),
            note.findtext("notehead"),
        )
        for instrument_id, note in notes_by_instrument.items()
    }
    assert positions["P1-I36"] == ("F", "4", "2", "down", None)
    assert positions["P1-I38"] == ("C", "5", "1", "up", None)
    assert positions["P1-I42"] == ("G", "5", "1", "up", "x")
    assert positions["P1-I46"] == ("G", "5", "1", "up", "x")
    assert positions["P1-I45"] == ("D", "5", "1", "up", None)
    assert positions["P1-I49"] == ("A", "5", "1", "up", "x")
    assert positions["P1-I36"][:2] != positions["P1-I38"][:2]
    assert positions["P1-I38"][:2] != positions["P1-I45"][:2]
    assert positions["P1-I42"][:2] != positions["P1-I49"][:2]


def test_musicxml_generator_keeps_voice_durations_measure_aligned(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_layered_events(events_path)

    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")
    measure = ET.parse(result.musicxml_path).getroot().find("./part/measure")
    assert measure is not None

    durations_by_voice = {"1": 0, "2": 0}
    for note in measure.findall("note"):
        if note.find("chord") is not None:
            continue
        voice = note.findtext("voice")
        if voice in durations_by_voice:
            durations_by_voice[voice] += int(note.findtext("duration"))

    assert durations_by_voice == {"1": 1920, "2": 1920}


def test_musicxml_generator_uses_readable_chart_events_for_dense_transcriptions(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_dense_chart_events(events_path)

    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")
    chart_payload = json.loads(result.chart_events_path.read_text(encoding="utf-8"))

    assert result.event_count == 160
    assert result.chart_event_count < result.event_count
    assert chart_payload["event_count"] == result.chart_event_count
    assert result.chart_summary["mode"] == "readable_drum_chart_v3"
    assert result.chart_summary["readability_verdict"] in {
        "readable_chart_candidate",
        "needs_manual_arrangement",
        "still_too_dense",
    }
    assert result.chart_summary["original_event_count"] == 160
    assert result.chart_summary["chart_event_count"] < 40
    assert result.chart_summary["max_visible_notes_per_measure"] <= 8
    assert result.chart_summary["dense_measures_before"] == 2
    assert result.chart_summary["dense_measures_after"] == 0
    assert result.chart_summary["preserved_counts"]["kick"] > 0
    assert result.chart_summary["preserved_counts"]["snare"] > 0
    assert result.chart_summary["preserved_counts"]["closed_hat"] > 0
    assert result.chart_summary["dropped_counts"]["tom"] > 0
    assert result.chart_summary["dropped_counts"]["cymbal"] > 0
    assert chart_payload["measures"]


def test_readable_chart_v2_remains_available_for_compatible_rendering(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_readable_v2_events(events_path)

    result = MusicXmlGenerator(NotationConfig(chart_mode="readable_drum_chart_v2")).generate(events_path, tmp_path / "notation")
    chart_payload = json.loads(result.chart_events_path.read_text(encoding="utf-8"))
    chart_events = chart_payload["events"]
    root = ET.parse(result.musicxml_path).getroot()

    assert result.chart_summary["mode"] == "readable_drum_chart_v2"
    assert result.chart_summary["repeat_measure_count"] == 0
    assert result.chart_summary["repeat_measure_indices"] == []
    assert result.chart_summary["fill_measure_count"] == 0
    assert result.chart_summary["max_visible_notes_per_measure"] <= 8
    assert root.find(".//measure-repeat") is None
    assert root.find(".//words[.='sim.']") is None

    assert chart_events
    assert not any(note.findtext("notehead") == "slash" for note in root.findall(".//note"))


def test_readable_chart_v3_writes_each_groove_measure_without_repeat_notation(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_readable_v3_section_events(events_path)

    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")
    chart_payload = json.loads(result.chart_events_path.read_text(encoding="utf-8"))
    root = ET.parse(result.musicxml_path).getroot()
    measures = chart_payload["measures"]
    chart_events = chart_payload["events"]

    assert result.chart_summary["mode"] == "readable_drum_chart_v3"
    assert result.chart_summary["repeat_measure_count"] == 0
    assert result.chart_summary["repeat_measure_indices"] == []
    assert result.chart_summary["complete_core_groove_measure_count"] == 8
    assert result.chart_summary["chart_hihat_evidence_measure_count"] == 8
    assert result.chart_summary["hihat_rendered_measure_count"] == 8
    assert result.chart_summary["fill_measure_count"] == 1
    assert all(item["visible_onset_count"] <= 8 for item in measures)
    assert {item["render_kind"] for item in measures} <= {"groove", "fill", "break", "rest"}
    assert not any(event["drum"] == "snare" and event["tick"] % 1920 == 120 for event in chart_events)
    assert not any(event["drum"] == "tom" and event["tick"] < 8 * 1920 for event in chart_events)
    assert any(event["drum"] == "tom" and event["tick"] >= 8 * 1920 for event in chart_events)
    assert root.find(".//measure-repeat") is None
    assert root.find(".//words[.='sim.']") is None
    assert not any(note.findtext("notehead") == "slash" for note in root.findall(".//note"))
    for measure_index in range(8):
        measure_events = [event for event in chart_events if event["tick"] // 1920 == measure_index]
        assert {event["drum"] for event in measure_events} >= {"kick", "snare", "closed_hat"}
        xml_measure = root.find(f"./part/measure[@number='{measure_index + 1}']")
        assert xml_measure is not None
        assert any(note.findtext("notehead") == "x" for note in xml_measure.findall("note"))
        durations_by_voice = {"1": 0, "2": 0}
        for note in xml_measure.findall("note"):
            if note.find("chord") is None and note.findtext("voice") in durations_by_voice:
                durations_by_voice[note.findtext("voice")] += int(note.findtext("duration"))
        assert durations_by_voice == {"1": 1920, "2": 1920}


def test_readable_chart_v3_marks_insufficient_hihat_evidence_as_needing_manual_arrangement(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    events = []
    for measure in range(3):
        base = measure * 1920
        events.extend(
            [
                {"tick": base, "drum": "kick", "velocity": 100},
                {"tick": base + 480, "drum": "snare", "velocity": 100},
                {"tick": base + 120, "drum": "closed_hat", "velocity": 80},
            ]
        )
    events_path.write_text(
        json.dumps(
            {
                "ticks_per_beat": 480,
                "estimated_bpm": 120.0,
                "time_signature": "4/4",
                "events": events,
            }
        ),
        encoding="utf-8",
    )

    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")

    assert result.chart_summary["readability_verdict"] == "needs_manual_arrangement"
    assert "chart_hihat_evidence_insufficient" in result.chart_summary["warnings"]
    assert result.chart_summary["hihat_rendered_measure_count"] == 3
    chart_payload = json.loads(result.chart_events_path.read_text(encoding="utf-8"))
    for measure_index in range(3):
        measure_events = [event for event in chart_payload["events"] if event["tick"] // 1920 == measure_index]
        assert {event["drum"] for event in measure_events} >= {"kick", "snare", "closed_hat"}


def test_readable_chart_v3_preserves_off_backbeat_core_evidence_without_inventing_events(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    events_path.write_text(
        json.dumps(
            {
                "ticks_per_beat": 480,
                "estimated_bpm": 120.0,
                "time_signature": "4/4",
                "events": [
                    {"tick": 120, "drum": "kick", "velocity": 92},
                    {"tick": 1080, "drum": "kick", "velocity": 88},
                    {"tick": 80, "drum": "snare", "velocity": 95},
                    {"tick": 1040, "drum": "snare", "velocity": 90},
                    *[
                        {"tick": tick, "drum": "closed_hat", "velocity": 80}
                        for tick in range(0, 1920, 240)
                    ],
                    {"tick": 1500, "drum": "tom", "velocity": 100},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")
    chart = json.loads(result.chart_events_path.read_text(encoding="utf-8"))
    events = chart["events"]

    assert {event["drum"] for event in events} >= {"kick", "snare", "closed_hat"}
    assert len([event for event in events if event["drum"] == "kick"]) == 2
    assert len([event for event in events if event["drum"] == "snare"]) == 2
    assert all(event["tick"] % 240 == 0 for event in events if event["drum"] in {"kick", "snare"})
    assert not any(event["drum"] == "tom" for event in events)


def test_rhythm_normalization_writes_eighth_groove_chords_without_sixteenth_fragments(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_readable_v3_section_events(events_path)

    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")
    root = ET.parse(result.musicxml_path).getroot()
    measure = root.find("./part/measure[@number='1']")
    assert measure is not None

    notes = measure.findall("note")
    assert any(
        note.find("chord") is not None and note.find("instrument") is not None and note.find("instrument").get("id") == "P1-I38"
        for note in notes
    )
    assert any(
        note.find("instrument") is not None and note.find("instrument").get("id") == "P1-I42" and note.findtext("type") == "eighth"
        for note in notes
    )
    assert not any(note.findtext("type") == "16th" for note in notes)
    for voice in ("1", "2"):
        assert sum(
            int(note.findtext("duration"))
            for note in notes
            if note.find("chord") is None and note.findtext("voice") == voice
        ) == 1920
    assert result.chart_summary["groove_eighth_note_count"] > 0
    assert result.chart_summary["groove_sixteenth_note_count"] == 0
    assert result.chart_summary["measures_with_fragmented_rests"] == 0


def test_rhythm_normalization_uses_quarter_hat_pulse_and_merged_rests_for_sparse_groove(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    events = []
    for tick in (0, 480, 960, 1440):
        events.append({"tick": tick, "drum": "closed_hat", "velocity": 90})
    events.extend(
        [
            {"tick": 0, "drum": "kick", "velocity": 100},
            {"tick": 960, "drum": "kick", "velocity": 100},
            {"tick": 480, "drum": "snare", "velocity": 100},
            {"tick": 1440, "drum": "snare", "velocity": 100},
        ]
    )
    events_path.write_text(
        json.dumps({"ticks_per_beat": 480, "estimated_bpm": 120.0, "time_signature": "4/4", "events": events}),
        encoding="utf-8",
    )

    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")
    root = ET.parse(result.musicxml_path).getroot()
    measure = root.find("./part/measure[@number='1']")
    assert measure is not None
    hats = [
        note
        for note in measure.findall("note")
        if note.find("instrument") is not None and note.find("instrument").get("id") == "P1-I42"
    ]
    assert len(hats) == 4
    assert all(note.findtext("type") == "quarter" for note in hats)
    assert not any(note.find("rest") is not None and note.findtext("type") == "16th" for note in measure.findall("note"))
    assert result.chart_summary["measures_with_fragmented_rests"] == 0


def test_rhythm_normalization_allows_sixteenths_only_in_credible_fill_tail(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_readable_v3_section_events(events_path)

    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")
    root = ET.parse(result.musicxml_path).getroot()
    groove_measure = root.find("./part/measure[@number='1']")
    fill_measure = root.find("./part/measure[@number='9']")
    assert groove_measure is not None
    assert fill_measure is not None
    assert not any(note.findtext("type") == "16th" for note in groove_measure.findall("note"))
    fill_sixteenths = [note for note in fill_measure.findall("note") if note.findtext("type") == "16th"]
    fill_sixteenth_notes = [note for note in fill_sixteenths if note.find("instrument") is not None]
    assert fill_sixteenth_notes
    assert all(note.find("instrument").get("id") in {"P1-I45", "P1-I38"} for note in fill_sixteenth_notes)
    assert result.chart_summary["fill_sixteenth_note_count"] > 0


def test_musicxml_tempo_override_is_reported_without_changing_source_events(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_events(events_path)

    result = MusicXmlGenerator(NotationConfig(tempo_bpm_override=130.0)).generate(events_path, tmp_path / "notation")
    root = ET.parse(result.musicxml_path).getroot()
    chart_payload = json.loads(result.chart_events_path.read_text(encoding="utf-8"))

    assert root.findtext("./part/measure/direction/direction-type/metronome/per-minute") == "130"
    assert root.find("./part/measure/direction/sound").get("tempo") == "130.0"
    assert result.tempo_bpm == 130.0
    assert result.tempo_source == "manual_override"
    assert chart_payload["tempo_bpm"] == 130.0
    assert chart_payload["tempo_source"] == "manual_override"


def test_score_artifact_validation_reports_musicxml_and_optional_pdf(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_events(events_path)
    musicxml = MusicXmlGenerator().generate(events_path, tmp_path / "notation")

    musicxml_validation = validate_musicxml_artifact(musicxml.musicxml_path)
    pdf_validation = validate_pdf_artifact(None)

    assert musicxml_validation == {"available": True, "parseable": True, "error_code": None, "warnings": []}
    assert pdf_validation == {
        "available": False,
        "optional": True,
        "openable": None,
        "error_code": "pdf_unavailable",
        "warnings": ["pdf_optional_unavailable"],
    }


def test_score_artifact_validation_rejects_invalid_musicxml_and_pdf_header(tmp_path) -> None:
    musicxml_path = tmp_path / "score.musicxml"
    pdf_path = tmp_path / "score.pdf"
    musicxml_path.write_text("<not-score />", encoding="utf-8")
    pdf_path.write_bytes(b"not pdf")

    musicxml_validation = validate_musicxml_artifact(musicxml_path)
    pdf_validation = validate_pdf_artifact(pdf_path)

    assert musicxml_validation["available"] is True
    assert musicxml_validation["parseable"] is True
    assert "musicxml_root_unexpected" in musicxml_validation["warnings"]
    assert pdf_validation["openable"] is False
    assert pdf_validation["error_code"] == "pdf_header_invalid"


def test_pdf_exporter_reports_missing_renderer(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_events(events_path)
    musicxml = MusicXmlGenerator().generate(events_path, tmp_path / "notation")

    try:
        MuseScorePdfExporter(renderer_binary="definitely-not-musescore").export(
            musicxml.musicxml_path,
            tmp_path / "notation",
        )
    except Exception as exc:
        assert getattr(exc, "code") == "PDF_RENDERER_NOT_AVAILABLE"
    else:
        raise AssertionError("expected PDF_RENDERER_NOT_AVAILABLE")


def test_pdf_exporter_accepts_nonzero_exit_when_pdf_exists(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_events(events_path)
    musicxml = MusicXmlGenerator().generate(events_path, tmp_path / "notation")

    def runner(command, **kwargs):
        pdf_path = Path(command[2])
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return subprocess.CompletedProcess(command, 1, "", "renderer shutdown warning")

    result = MuseScorePdfExporter(
        renderer_binary=sys.executable,
        runner=runner,
    ).export(musicxml.musicxml_path, tmp_path / "notation")

    assert result.pdf_path.exists()
    assert result.warnings
    assert result.warnings[0].startswith("renderer_nonzero_exit:")


def test_pdf_exporter_fails_nonzero_exit_without_pdf(tmp_path) -> None:
    events_path = tmp_path / "drum_events.json"
    _write_events(events_path)
    musicxml = MusicXmlGenerator().generate(events_path, tmp_path / "notation")

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "renderer failed")

    try:
        MuseScorePdfExporter(
            renderer_binary=sys.executable,
            runner=runner,
        ).export(musicxml.musicxml_path, tmp_path / "notation")
    except Exception as exc:
        assert getattr(exc, "code") == "PDF_EXPORT_FAILED"
    else:
        raise AssertionError("expected PDF_EXPORT_FAILED")


def test_local_runner_writes_validation_summary_to_pipeline_log(tmp_path) -> None:
    source = Path("tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav")
    output_dir = tmp_path / "output"

    result = LocalPipelineRunner(LocalPipelineConfig(mock_ai=True)).run(source, output_dir)

    payload = json.loads(result.log_path.read_text(encoding="utf-8"))
    assert payload["validation"]["musicxml"]["parseable"] is True
    assert payload["quality"]["notation_readability"]["layout_profile"] == "standard_drum_v1"
    assert payload["quality"]["notation_readability"]["has_hand_voice"] is True
    assert payload["quality"]["notation_readability"]["has_foot_voice"] is True
    assert payload["quality"]["notation_chart"]["mode"] == "readable_drum_chart_v3"
    assert payload["quality"]["notation_chart"]["readability_verdict"] == "needs_manual_arrangement"
    # Sparse hi-hat evidence may be expanded to a readable quarter-note pulse;
    # readability is bounded by visible onset slots rather than raw event count.
    assert payload["quality"]["notation_chart"]["max_visible_notes_per_measure"] <= 8
    assert payload["validation"]["pdf"] == {
        "available": False,
        "optional": True,
        "openable": None,
        "error_code": "pdf_unavailable",
        "warnings": ["pdf_optional_unavailable"],
    }
    assert payload["validation"]["visual_qa"]["status"] == "not_requested"


def test_local_runner_reports_gui_session_unavailable_without_failing_musicxml(monkeypatch, tmp_path) -> None:
    source = Path("tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav")

    class GuiUnavailableRenderer:
        def __init__(self, **_kwargs) -> None:
            pass

        def render(self, *_args, **_kwargs) -> MuseScoreVisualQaResult:
            return MuseScoreVisualQaResult(
                "musescore_gui_session_unavailable",
                "musescore_gui_session_unavailable",
            )

    monkeypatch.setattr("ai_pipeline.local_runner.MuseScoreVisualQaRenderer", GuiUnavailableRenderer)
    result = LocalPipelineRunner(LocalPipelineConfig(mock_ai=True, visual_qa=True)).run(source, tmp_path / "output")
    payload = json.loads(result.log_path.read_text(encoding="utf-8"))

    assert result.status == "completed"
    assert payload["validation"]["musicxml"]["parseable"] is True
    assert payload["validation"]["visual_qa"] == {
        "status": "musescore_gui_session_unavailable",
        "reason_code": "musescore_gui_session_unavailable",
        "pdf_available": False,
        "first_page_png_available": False,
    }


def test_local_runner_reports_manual_tempo_override(tmp_path) -> None:
    source = Path("tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav")
    result = LocalPipelineRunner(LocalPipelineConfig(mock_ai=True, tempo_bpm=130.0)).run(source, tmp_path / "output")
    payload = json.loads(result.log_path.read_text(encoding="utf-8"))
    notation_report = next(stage["report"] for stage in payload["stages"] if stage["name"] == "notation_generation")

    assert notation_report["tempo_bpm"] == 130.0
    assert notation_report["tempo_source"] == "manual_override"
    assert payload["quality"]["tempo_bpm"] == 130.0
    assert payload["quality"]["tempo_source"] == "manual_override"
