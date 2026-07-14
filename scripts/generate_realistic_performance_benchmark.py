from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

import mido

from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate realistic synthetic ground-truth drum benchmarks with FluidSynth")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--soundfont", type=Path, default=_env_path("GROOVESCRIBE_BENCHMARK_SOUNDFONT"))
    parser.add_argument("--fluidsynth", default=os.environ.get("GROOVESCRIBE_FLUIDSYNTH_BIN", "fluidsynth"))
    parser.add_argument("--ffmpeg", default=os.environ.get("GROOVESCRIBE_FFMPEG_BIN", "ffmpeg"))
    return parser.parse_args()


def generate(config: argparse.Namespace, *, run=subprocess.run, which=shutil.which) -> dict:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    blocked = _blocker(config, which)
    if blocked:
        report = {"schema_version": "1.0", "status": "blocked", "reason": blocked, "manifest_name": None}
        _write_json(config.output_dir / "realistic_benchmark_status.json", report)
        return report

    profiles = [
        ("eighth_hat_backbeat", _groove(hat_step=240, fast=False, fill=False), "drum_only"),
        ("quarter_hat_backbeat", _groove(hat_step=480, fast=False, fill=False), "drum_only"),
        ("tom_fill", _groove(hat_step=240, fast=False, fill=True), "drum_only"),
        ("fast_groove", _groove(hat_step=240, fast=True, fill=False), "drum_only"),
        ("full_mix_backbeat", _groove(hat_step=240, fast=False, fill=False), "full_mix"),
    ]
    items = []
    for item_id, events, input_type in profiles:
        midi = config.output_dir / f"{item_id}.ground_truth.mid"
        drum_audio = config.output_dir / f"{item_id}.drums.wav"
        audio = config.output_dir / f"{item_id}.wav"
        write_drum_midi(midi, tuple(events), ticks_per_beat=480, tempo_bpm=120.0)
        rendered = run(
            [config.fluidsynth, "-ni", "-F", str(drum_audio), "-r", "44100", str(config.soundfont), str(midi)],
            capture_output=True,
            text=True,
            check=False,
        )
        if rendered.returncode != 0 or not drum_audio.exists():
            report = {"schema_version": "1.0", "status": "blocked", "reason": "soundfont_render_failed", "manifest_name": None}
            _write_json(config.output_dir / "realistic_benchmark_status.json", report)
            return report
        if input_type == "full_mix":
            backing_midi = config.output_dir / f"{item_id}.backing.mid"
            backing_audio = config.output_dir / f"{item_id}.backing.wav"
            _write_backing_midi(backing_midi)
            backing_rendered = run(
                [config.fluidsynth, "-ni", "-F", str(backing_audio), "-r", "44100", str(config.soundfont), str(backing_midi)],
                capture_output=True,
                text=True,
                check=False,
            )
            if backing_rendered.returncode != 0 or not backing_audio.exists():
                report = {"schema_version": "1.0", "status": "blocked", "reason": "soundfont_backing_render_failed", "manifest_name": None}
                _write_json(config.output_dir / "realistic_benchmark_status.json", report)
                return report
            mixed = run(
                [config.ffmpeg, "-y", "-i", str(drum_audio), "-i", str(backing_audio), "-filter_complex", "[0:a][1:a]amix=inputs=2:weights='1 0.30'", "-t", "8", str(audio)],
                capture_output=True,
                text=True,
                check=False,
            )
            if mixed.returncode != 0 or not audio.exists():
                report = {"schema_version": "1.0", "status": "blocked", "reason": "full_mix_render_failed", "manifest_name": None}
                _write_json(config.output_dir / "realistic_benchmark_status.json", report)
                return report
        else:
            drum_audio.replace(audio)
        items.append(
            {
                "id": item_id,
                "audio_path": str(audio),
                "ground_truth_midi_path": str(midi),
                "tempo_bpm": 120,
                "time_signature": "4/4",
                "input_type": input_type,
                "license": "generated_from_configured_soundfont",
                "source": "GrooveScribe realistic synthetic benchmark",
                "renderer": "soundfont",
                "calibration_eligible": True,
                "acceptance": {
                    "minimum_f1": 0.75,
                    "minimum_per_drum_f1": {"kick": 0.75, "snare": 0.75, "closed_hat": 0.65},
                    "minimum_core_groove_accuracy": 0.75,
                    "maximum_mean_timing_error_ticks": 60,
                },
            }
        )
    manifest = {"schema_version": "1.0", "kind": "realistic_synthetic_ground_truth_v2", "items": items}
    manifest_path = config.output_dir / "realistic_performance_benchmark_manifest.json"
    _write_json(manifest_path, manifest)
    report = {"schema_version": "1.0", "status": "completed", "reason": None, "manifest_name": manifest_path.name}
    _write_json(config.output_dir / "realistic_benchmark_status.json", report)
    return report


def _blocker(config: argparse.Namespace, which) -> str | None:
    if config.soundfont is None or not config.soundfont.exists():
        return "soundfont_not_configured"
    if which(config.fluidsynth) is None:
        return "fluidsynth_unavailable"
    if which(config.ffmpeg) is None:
        return "ffmpeg_unavailable"
    return None


def _groove(*, hat_step: int, fast: bool, fill: bool) -> list[ProcessedDrumEvent]:
    events: list[ProcessedDrumEvent] = []
    for measure in range(4):
        base = measure * 1920
        for tick in range(0, 1920, hat_step):
            events.append(ProcessedDrumEvent(tick=base + tick, note=42, drum="closed_hat", velocity=78))
        kick_ticks = (0, 720, 960) if fast else (0, 960)
        for tick in kick_ticks:
            events.append(ProcessedDrumEvent(tick=base + tick, note=36, drum="kick", velocity=105))
        for tick in (480, 1440):
            events.append(ProcessedDrumEvent(tick=base + tick, note=38, drum="snare", velocity=98))
    if fill:
        events.extend(ProcessedDrumEvent(tick=3 * 1920 + tick, note=45, drum="tom", velocity=96) for tick in (1440, 1560, 1680, 1800))
    return events


def _write_backing_midi(path: Path) -> None:
    """Create a deterministic two-instrument backing without synthetic sine tones."""

    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    track.append(mido.Message("program_change", channel=0, program=4, time=0))  # Electric piano.
    track.append(mido.Message("program_change", channel=1, program=33, time=0))  # Electric bass.
    for measure in range(4):
        for beat, chord in enumerate(((60, 64, 67), (57, 60, 64), (65, 69, 72), (55, 59, 62))):
            # Previous chord releases at tick 420, leaving a 60-tick gap in a 480-tick beat.
            delta = 0 if beat == 0 and measure == 0 else 60
            track.append(mido.Message("note_on", channel=0, note=chord[0], velocity=52, time=delta))
            track.append(mido.Message("note_on", channel=0, note=chord[1], velocity=46, time=0))
            track.append(mido.Message("note_on", channel=0, note=chord[2], velocity=42, time=0))
            track.append(mido.Message("note_on", channel=1, note=chord[0] - 24, velocity=58, time=0))
            track.append(mido.Message("note_off", channel=0, note=chord[0], velocity=0, time=420))
            track.append(mido.Message("note_off", channel=0, note=chord[1], velocity=0, time=0))
            track.append(mido.Message("note_off", channel=0, note=chord[2], velocity=0, time=0))
            track.append(mido.Message("note_off", channel=1, note=chord[0] - 24, velocity=0, time=0))
    track.append(mido.MetaMessage("end_of_track", time=0))
    midi.save(path)


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    result = generate(parse_args())
    print(json.dumps({"status": result["status"], "reason": result["reason"], "manifest_name": result["manifest_name"]}, ensure_ascii=False))
