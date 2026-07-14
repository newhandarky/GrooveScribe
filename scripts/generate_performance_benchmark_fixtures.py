from __future__ import annotations

import argparse
import json
import math
import struct
import wave
from pathlib import Path

from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate legal synthetic audio/MIDI performance benchmark fixtures")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fixtures = [
        ("stable_eighth_groove", _groove(fill=False), "drum_only"),
        ("simple_fill_groove", _groove(fill=True), "drum_only"),
        ("synthetic_full_mix", _groove(fill=False), "full_mix"),
    ]
    items = []
    for fixture_id, events, input_type in fixtures:
        midi_path = args.output_dir / f"{fixture_id}.ground_truth.mid"
        audio_path = args.output_dir / f"{fixture_id}.wav"
        write_drum_midi(midi_path, tuple(events), ticks_per_beat=480, tempo_bpm=120.0)
        _write_audio(audio_path, events, full_mix=input_type == "full_mix")
        items.append(
            {
                "id": fixture_id,
                "audio_path": str(audio_path),
                "ground_truth_midi_path": str(midi_path),
                "tempo_bpm": 120,
                "time_signature": "4/4",
                "input_type": input_type,
                "license": "generated_synthetic",
                "source": "GrooveScribe synthetic generator",
                "renderer": "synthetic_signal",
                "calibration_eligible": False,
                "acceptance": {"minimum_f1": 0.9, "maximum_mean_timing_error_ticks": 60},
            }
        )
    manifest = {"schema_version": "1.0", "items": items}
    manifest_path = args.output_dir / "performance_benchmark_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "completed", "manifest_name": manifest_path.name}, ensure_ascii=False))
    return 0


def _groove(*, fill: bool) -> list[ProcessedDrumEvent]:
    events = []
    for measure in range(4):
        base = measure * 1920
        for slot in range(8):
            events.append(ProcessedDrumEvent(tick=base + slot * 240, note=42, drum="closed_hat", velocity=78))
        events.extend(
            [
                ProcessedDrumEvent(tick=base, note=36, drum="kick", velocity=105),
                ProcessedDrumEvent(tick=base + 960, note=36, drum="kick", velocity=100),
                ProcessedDrumEvent(tick=base + 480, note=38, drum="snare", velocity=98),
                ProcessedDrumEvent(tick=base + 1440, note=38, drum="snare", velocity=98),
            ]
        )
    if fill:
        events.extend(
            ProcessedDrumEvent(tick=3 * 1920 + offset, note=45, drum="tom", velocity=96)
            for offset in (1440, 1560, 1680, 1800)
        )
    return events


def _write_audio(path: Path, events: list[ProcessedDrumEvent], *, full_mix: bool) -> None:
    rate, duration = 44_100, 8.2
    samples = [0.0] * int(rate * duration)
    for event in events:
        start = int(event.tick / 480 * 0.5 * rate)
        frequency = {"kick": 85, "snare": 220, "closed_hat": 3600, "tom": 145}.get(event.drum, 440)
        length = int(rate * (0.11 if event.drum == "kick" else 0.045))
        for offset in range(length):
            if start + offset >= len(samples):
                break
            envelope = 1 - offset / length
            samples[start + offset] += math.sin(2 * math.pi * frequency * offset / rate) * envelope * 0.36
    if full_mix:
        for index in range(len(samples)):
            samples[index] += math.sin(2 * math.pi * 220 * index / rate) * 0.09
            samples[index] += math.sin(2 * math.pi * 329.63 * index / rate) * 0.05
    packed = struct.pack(f"<{len(samples)}h", *(max(-32767, min(32767, int(value * 32767))) for value in samples))
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(packed)


if __name__ == "__main__":
    raise SystemExit(main())
