import json
from pathlib import Path

from ai_pipeline.midi.mapping import DRUM_TAXONOMY_ID, map_to_general_midi_drum, normalize_drum_counts
from ai_pipeline.midi.postprocessor import MidiPostProcessor
from ai_pipeline.midi.quality import evaluate_drum_draft_quality
from ai_pipeline.midi.simple_midi import parse_midi, write_drum_midi
from ai_pipeline.midi.types import MidiPostProcessConfig, ProcessedDrumEvent
from ai_pipeline.notation.musicxml import MusicXmlGenerator
from ai_pipeline.transcription.midi_validation import count_note_on_events


def _write_raw_midi(path: Path) -> None:
    events = (
        ProcessedDrumEvent(tick=0, note=35, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=58, note=36, drum="kick", velocity=90),
        ProcessedDrumEvent(tick=122, note=38, drum="snare", velocity=80),
        ProcessedDrumEvent(tick=241, note=42, drum="closed_hat", velocity=70),
    )
    write_drum_midi(path, events, ticks_per_beat=480, tempo_bpm=120.0, default_duration_ticks=60)


def test_general_midi_drum_mapping() -> None:
    assert map_to_general_midi_drum(35).note == 36
    assert map_to_general_midi_drum(38).drum == "snare"
    assert map_to_general_midi_drum(42).drum == "hi_hat"
    assert map_to_general_midi_drum(44).drum == "hi_hat"
    assert map_to_general_midi_drum(46).drum == "hi_hat"
    assert map_to_general_midi_drum(47).drum == "tom"
    assert map_to_general_midi_drum(10) is None


def test_hat_notes_normalize_through_postprocess_notation_and_performance_midi(tmp_path) -> None:
    raw_midi = tmp_path / "raw_hats.mid"
    write_drum_midi(
        raw_midi,
        (
            ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
            ProcessedDrumEvent(tick=240, note=42, drum="closed_hat", velocity=80),
            ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=100),
            ProcessedDrumEvent(tick=720, note=44, drum="pedal_hat", velocity=80),
            ProcessedDrumEvent(tick=960, note=46, drum="open_hat", velocity=80),
        ),
        ticks_per_beat=480,
        tempo_bpm=120.0,
    )

    processed = MidiPostProcessor().process(raw_midi, tmp_path / "processed")
    notation = MusicXmlGenerator().generate(processed.drum_events_path, tmp_path / "notation")
    chart = json.loads(notation.chart_events_path.read_text(encoding="utf-8"))
    performance = parse_midi(notation.performance_midi_path)

    assert [event.drum for event in processed.events].count("hi_hat") == 3
    assert all(event.drum not in {"closed_hat", "open_hat", "pedal_hat"} for event in processed.events)
    assert all(event["drum"] not in {"closed_hat", "open_hat", "pedal_hat"} for event in chart["events"])
    assert any(event["drum"] == "hi_hat" for event in chart["events"])
    assert 42 in {event.note for event in performance.notes}
    assert 44 not in {event.note for event in performance.notes}
    assert 46 not in {event.note for event in performance.notes}


def test_postprocessor_quantizes_dedupes_and_writes_artifacts(tmp_path) -> None:
    raw_midi = tmp_path / "raw_drum.mid"
    _write_raw_midi(raw_midi)

    processor = MidiPostProcessor(
        MidiPostProcessConfig(
            grid_subdivisions_per_beat=4,
            dedupe_window_ticks=120,
            velocity_floor=1,
            default_duration_ticks=60,
        )
    )
    result = processor.process(raw_midi, tmp_path / "out")

    assert result.processed_midi_path.exists()
    assert result.drum_events_path.exists()
    assert count_note_on_events(result.processed_midi_path) == 3
    assert [event.tick for event in result.events] == [0, 120, 240]
    assert [event.drum for event in result.events] == ["kick", "snare", "hi_hat"]

    payload = json.loads(result.drum_events_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["drum_taxonomy"] == DRUM_TAXONOMY_ID
    assert payload["event_count"] == 3
    assert payload["events"][0]["midi_note"] == 36
    assert payload["raw_note_histogram"] == {"35": 1, "36": 1, "38": 1, "42": 1}
    assert payload["processed_drum_counts"] == {"hi_hat": 1, "kick": 1, "snare": 1}
    assert "repeated_close_events_deduped" in payload["warnings"]
    assert "sparse_transcription" in payload["warnings"]
    assert "too_few_events" in payload["warnings"]


def test_legacy_counts_merge_and_unknown_labels_are_dropped() -> None:
    assert normalize_drum_counts(
        {"kick": 2, "closed_hat": 3, "open_hat": 4, "pedal_hat": 5, "unsupported": 9}
    ) == {"hi_hat": 12, "kick": 2}


def test_postprocessor_warns_for_sparse_and_unbalanced_output(tmp_path) -> None:
    raw_midi = tmp_path / "raw_toms.mid"
    events = (
        ProcessedDrumEvent(tick=0, note=45, drum="tom", velocity=100),
        ProcessedDrumEvent(tick=480, note=45, drum="tom", velocity=100),
        ProcessedDrumEvent(tick=960, note=45, drum="tom", velocity=100),
        ProcessedDrumEvent(tick=1440, note=45, drum="tom", velocity=100),
    )
    write_drum_midi(raw_midi, events, ticks_per_beat=480, tempo_bpm=120.0)

    result = MidiPostProcessor().process(raw_midi, tmp_path / "out")

    assert result.report.processed_drum_counts == {"tom": 4}
    assert "mostly_tom_output" in result.report.warnings
    assert "raw_tom_dominant" in result.report.warnings
    assert "missing_core_groove" in result.report.warnings
    assert "no_usable_groove" in result.report.warnings
    assert "hihat_missing_likely" in result.report.warnings
    assert "no_snare_detected" in result.report.warnings


def test_postprocessor_does_not_remap_general_midi_tom_without_evidence(tmp_path) -> None:
    raw_midi = tmp_path / "raw_tom_47.mid"
    events = (
        ProcessedDrumEvent(tick=0, note=47, drum="tom", velocity=100),
        ProcessedDrumEvent(tick=480, note=47, drum="tom", velocity=100),
        ProcessedDrumEvent(tick=960, note=47, drum="tom", velocity=100),
        ProcessedDrumEvent(tick=1440, note=47, drum="tom", velocity=100),
    )
    write_drum_midi(raw_midi, events, ticks_per_beat=480, tempo_bpm=120.0)

    result = MidiPostProcessor().process(raw_midi, tmp_path / "out")

    assert result.report.raw_note_histogram == {47: 4}
    assert result.report.processed_drum_counts == {"tom": 4}
    assert {event.drum for event in result.events} == {"tom"}
    assert all(event.note == 45 for event in result.events)
    assert "mostly_tom_output" in result.report.warnings
    assert "no_snare_detected" in result.report.warnings


def test_tom_guard_is_disabled_by_default_and_preserves_output(tmp_path) -> None:
    raw_midi = tmp_path / "raw_with_toms.mid"
    events = _tom_guard_fixture_events()
    write_drum_midi(raw_midi, events, ticks_per_beat=480, tempo_bpm=120.0)

    result = MidiPostProcessor().process(raw_midi, tmp_path / "out")

    assert result.report.processed_drum_counts == {
        "hi_hat": 2,
        "kick": 2,
        "snare": 2,
        "tom": 5,
    }
    assert [event.drum for event in result.events].count("tom") == 5
    assert result.report.postprocess_filters["tom_false_positive"]["status"] == "disabled"


def test_tom_guard_drops_only_overlapping_toms_and_preserves_core_drums(tmp_path) -> None:
    raw_midi = tmp_path / "raw_with_toms.mid"
    events = _tom_guard_fixture_events()
    write_drum_midi(raw_midi, events, ticks_per_beat=480, tempo_bpm=120.0)

    result = MidiPostProcessor(
        MidiPostProcessConfig(
            tom_filter_enabled=True,
            tom_filter_preset="tom_guard_v1",
            tom_filter_target_max_ratio=0.30,
            tom_filter_core_overlap_window_ticks=1,
        )
    ).process(raw_midi, tmp_path / "out")

    counts = result.report.processed_drum_counts
    assert counts["kick"] == 2
    assert counts["snare"] == 2
    assert counts["hi_hat"] == 2
    assert counts["tom"] == 2
    assert all(event.drum != "tom" or event.note == 45 for event in result.events)
    assert not any(event.drum == "snare" and event.note == 45 for event in result.events)
    summary = result.report.postprocess_filters["tom_false_positive"]
    assert summary["status"] == "applied"
    assert summary["input_tom_count"] == 5
    assert summary["output_tom_count"] == 2
    assert summary["dropped_tom_count"] == 3
    assert "tom_false_positive_likely" not in result.report.warnings

    payload = json.loads(result.drum_events_path.read_text(encoding="utf-8"))
    assert payload["postprocess_filters"]["tom_false_positive"]["status"] == "applied"


def test_tom_guard_skips_when_core_groove_is_incomplete(tmp_path) -> None:
    raw_midi = tmp_path / "raw_missing_core.mid"
    events = (
        ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=0, note=47, drum="tom", velocity=80),
        ProcessedDrumEvent(tick=120, note=47, drum="tom", velocity=80),
        ProcessedDrumEvent(tick=240, note=47, drum="tom", velocity=80),
    )
    write_drum_midi(raw_midi, events, ticks_per_beat=480, tempo_bpm=120.0)

    result = MidiPostProcessor(
        MidiPostProcessConfig(tom_filter_enabled=True, tom_filter_preset="tom_guard_v1")
    ).process(raw_midi, tmp_path / "out")

    assert result.report.processed_drum_counts == {"kick": 1, "tom": 3}
    summary = result.report.postprocess_filters["tom_false_positive"]
    assert summary["status"] == "skipped_missing_core_groove"
    assert summary["dropped_tom_count"] == 0


def test_postprocessor_marks_kick_snare_only_as_hihat_limitation(tmp_path) -> None:
    raw_midi = tmp_path / "raw_kick_snare.mid"
    events = (
        ProcessedDrumEvent(tick=0, note=35, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=90),
        ProcessedDrumEvent(tick=960, note=35, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=1440, note=38, drum="snare", velocity=90),
    )
    write_drum_midi(raw_midi, events, ticks_per_beat=480, tempo_bpm=120.0)

    result = MidiPostProcessor().process(raw_midi, tmp_path / "out")

    assert result.report.processed_drum_counts == {"kick": 2, "snare": 2}
    assert "kick_snare_only" in result.report.warnings
    assert "hihat_missing_likely" in result.report.warnings
    assert "mostly_tom_output" not in result.report.warnings
    assert "no_snare_detected" not in result.report.warnings


def test_postprocessor_warns_for_repeated_close_events(tmp_path) -> None:
    raw_midi = tmp_path / "raw_repeated.mid"
    events = (
        ProcessedDrumEvent(tick=0, note=42, drum="closed_hat", velocity=80),
        ProcessedDrumEvent(tick=10, note=42, drum="closed_hat", velocity=100),
        ProcessedDrumEvent(tick=480, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=960, note=38, drum="snare", velocity=90),
        ProcessedDrumEvent(tick=1440, note=42, drum="closed_hat", velocity=90),
    )
    write_drum_midi(raw_midi, events, ticks_per_beat=480, tempo_bpm=120.0)

    result = MidiPostProcessor().process(raw_midi, tmp_path / "out")

    assert result.report.output_event_count == 4
    assert "repeated_close_events_deduped" in result.report.warnings


def test_quality_verdict_marks_mvp_candidate_when_core_drums_and_tom_ratio_are_strong() -> None:
    verdict = evaluate_drum_draft_quality(
        processed_drum_counts={"kick": 4, "snare": 4, "closed_hat": 8, "tom": 2},
        processed_event_count=18,
        quality_flags=[],
        musicxml_available=True,
        musicxml_parseable=True,
    )

    assert verdict["verdict"] == "mvp_candidate"
    assert verdict["usability_score"] == 5
    assert verdict["candidate_gate"]["status"] == "passed"


def test_quality_verdict_marks_draft_candidate_when_tom_false_positive_remains() -> None:
    verdict = evaluate_drum_draft_quality(
        processed_drum_counts={"kick": 2, "snare": 4, "closed_hat": 4, "tom": 6},
        processed_event_count=16,
        quality_flags=[],
        musicxml_available=True,
        musicxml_parseable=True,
    )

    assert verdict["verdict"] == "draft_candidate_needs_review"
    assert verdict["usability_score"] == 3
    assert verdict["candidate_gate"]["status"] == "passed"
    assert "tom_false_positive_likely" in verdict["limitations"]


def test_quality_verdict_rejects_no_snare_and_unparseable_musicxml() -> None:
    verdict = evaluate_drum_draft_quality(
        processed_drum_counts={"kick": 3, "closed_hat": 4, "tom": 2},
        processed_event_count=9,
        quality_flags=["no_snare_detected"],
        musicxml_available=True,
        musicxml_parseable=False,
    )

    assert verdict["verdict"] == "not_candidate"
    assert verdict["usability_score"] == 1
    assert verdict["candidate_gate"]["status"] == "failed"
    assert verdict["candidate_gate"]["blocking_flags"] == ["no_snare_detected"]
    assert "musicxml_unparseable" in verdict["limitations"]


def test_parse_processed_midi_round_trip(tmp_path) -> None:
    midi_path = tmp_path / "processed.mid"
    events = (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),)
    write_drum_midi(midi_path, events, ticks_per_beat=480)

    parsed = parse_midi(midi_path)
    assert parsed.ticks_per_beat == 480
    assert len(parsed.notes) == 1
    assert parsed.notes[0].note == 36


def _tom_guard_fixture_events() -> tuple[ProcessedDrumEvent, ...]:
    return (
        ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=105),
        ProcessedDrumEvent(tick=0, note=47, drum="tom", velocity=45),
        ProcessedDrumEvent(tick=120, note=42, drum="closed_hat", velocity=78),
        ProcessedDrumEvent(tick=120, note=47, drum="tom", velocity=48),
        ProcessedDrumEvent(tick=240, note=38, drum="snare", velocity=96),
        ProcessedDrumEvent(tick=240, note=47, drum="tom", velocity=50),
        ProcessedDrumEvent(tick=360, note=42, drum="closed_hat", velocity=74),
        ProcessedDrumEvent(tick=360, note=47, drum="tom", velocity=52),
        ProcessedDrumEvent(tick=480, note=36, drum="kick", velocity=102),
        ProcessedDrumEvent(tick=600, note=38, drum="snare", velocity=92),
        ProcessedDrumEvent(tick=900, note=47, drum="tom", velocity=95),
    )
