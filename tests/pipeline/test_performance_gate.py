from __future__ import annotations

import json
import struct
import wave
from pathlib import Path

from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent
from ai_pipeline.notation import MusicXmlGenerator
from ai_pipeline.notation.performance_gate import compare_performance_midi_to_ground_truth, evaluate_performance_score


def test_performance_gate_accepts_complete_aligned_chart(tmp_path: Path) -> None:
    events_path = tmp_path / "drum_events.json"
    events_path.write_text(json.dumps(_two_measure_groove()), encoding="utf-8")
    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")
    _write_click_stem(tmp_path / "drums.wav", [index * 0.25 for index in range(16)])

    gate = evaluate_performance_score(
        chart_events_path=result.chart_events_path,
        performance_midi_path=result.performance_midi_path,
        performance_musicxml_path=result.performance_musicxml_path,
        drums_stem_path=tmp_path / "drums.wav",
        gate_calibration={"status": "calibrated", "allow_performance_ready": True, "min_auto_onset_alignment": 0.7},
    )

    assert gate["verdict"] == "performance_ready"
    assert gate["delivery_allowed"] is True
    assert gate["midi"]["playback_ready"] is True
    assert gate["musicxml"]["parseable"] is True
    assert gate["rhythm"]["complete"] is True


def test_performance_gate_does_not_claim_ready_without_alignment(tmp_path: Path) -> None:
    events_path = tmp_path / "drum_events.json"
    events_path.write_text(json.dumps(_two_measure_groove()), encoding="utf-8")
    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")

    gate = evaluate_performance_score(
        chart_events_path=result.chart_events_path,
        performance_midi_path=result.performance_midi_path,
        performance_musicxml_path=result.performance_musicxml_path,
        drums_stem_path=None,
    )

    assert gate["verdict"] == "playable_but_low_confidence"
    assert "audio_onset_alignment_unavailable" in gate["blocking_issues"]


def test_performance_gate_fails_closed_without_calibration(tmp_path: Path) -> None:
    events_path = tmp_path / "drum_events.json"
    events_path.write_text(json.dumps(_two_measure_groove()), encoding="utf-8")
    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")
    _write_click_stem(tmp_path / "drums.wav", [index * 0.25 for index in range(16)])

    gate = evaluate_performance_score(
        chart_events_path=result.chart_events_path,
        performance_midi_path=result.performance_midi_path,
        performance_musicxml_path=result.performance_musicxml_path,
        drums_stem_path=tmp_path / "drums.wav",
    )

    assert gate["verdict"] == "playable_but_low_confidence"
    assert "gate_calibration_unavailable" in gate["blocking_issues"]


def test_performance_gate_rejects_tom_outside_fill(tmp_path: Path) -> None:
    payload = _two_measure_groove()
    payload["events"].append({"tick": 240, "drum": "tom", "velocity": 100})
    events_path = tmp_path / "drum_events.json"
    events_path.write_text(json.dumps(payload), encoding="utf-8")
    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")
    chart = json.loads(result.chart_events_path.read_text(encoding="utf-8"))
    chart["events"].append({"tick": 240, "drum": "tom", "velocity": 100})
    result.chart_events_path.write_text(json.dumps(chart), encoding="utf-8")

    gate = evaluate_performance_score(
        chart_events_path=result.chart_events_path,
        performance_midi_path=result.performance_midi_path,
        performance_musicxml_path=result.performance_musicxml_path,
        drums_stem_path=None,
    )

    assert gate["verdict"] == "not_ready"
    assert "tom_outside_fill" in gate["blocking_issues"]


def test_ground_truth_comparison_is_opt_in_and_reports_onset_metrics(tmp_path: Path) -> None:
    events_path = tmp_path / "drum_events.json"
    events_path.write_text(json.dumps(_two_measure_groove()), encoding="utf-8")
    result = MusicXmlGenerator().generate(events_path, tmp_path / "notation")

    comparison = compare_performance_midi_to_ground_truth(result.performance_midi_path, result.performance_midi_path)

    assert comparison["status"] == "measured"
    assert comparison["precision"] == 1.0
    assert comparison["recall"] == 1.0
    assert comparison["f1"] == 1.0


def test_ground_truth_comparison_normalizes_different_midi_tick_resolutions(tmp_path: Path) -> None:
    predicted = tmp_path / "performance.mid"
    expected = tmp_path / "ground_truth.mid"
    write_drum_midi(
        predicted,
        (
            ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
            ProcessedDrumEvent(tick=220, note=38, drum="snare", velocity=100),
        ),
        ticks_per_beat=220,
    )
    write_drum_midi(
        expected,
        (
            ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
            ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=100),
        ),
        ticks_per_beat=480,
    )

    comparison = compare_performance_midi_to_ground_truth(predicted, expected)

    assert comparison["f1"] == 1.0
    assert comparison["mean_timing_error_ticks"] == 0.0
    assert comparison["timing_unit"] == "normalized_ticks_480_tpq"


def _two_measure_groove() -> dict:
    events = []
    for measure in range(2):
        base = measure * 1920
        for slot in range(8):
            events.append({"tick": base + slot * 240, "drum": "closed_hat", "velocity": 80})
        events.extend(
            [
                {"tick": base, "drum": "kick", "velocity": 100},
                {"tick": base + 480, "drum": "snare", "velocity": 100},
                {"tick": base + 960, "drum": "kick", "velocity": 100},
                {"tick": base + 1440, "drum": "snare", "velocity": 100},
            ]
        )
    return {"ticks_per_beat": 480, "estimated_bpm": 120.0, "time_signature": "4/4", "events": events}


def _write_click_stem(path: Path, onsets: list[float]) -> None:
    sample_rate = 44_100
    samples = [0] * int(sample_rate * 4.1)
    for onset in onsets:
        start = int(onset * sample_rate)
        for offset in range(180):
            if start + offset < len(samples):
                samples[start + offset] = 24_000
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(struct.pack(f"<{len(samples)}h", *samples))
