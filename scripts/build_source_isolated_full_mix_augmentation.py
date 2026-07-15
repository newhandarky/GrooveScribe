from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import librosa
import mido
import numpy as np
import soundfile as sf

from ai_pipeline.source_separation.demucs import DemucsSourceSeparator


_SAMPLE_RATE = 44_100


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build private source-isolated synthetic full-mix Demucs-stem augmentation for model training."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--soundfont", type=Path, required=True)
    parser.add_argument("--fluidsynth", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-train-items", type=int, default=12)
    parser.add_argument("--max-validation-items", type=int, default=3)
    parser.add_argument("--demucs-device", default="cpu")
    return parser.parse_args()


def build(config: argparse.Namespace, *, runner=subprocess.run) -> dict[str, Any]:
    manifest = _read_json(config.manifest)
    reason = _validate_source_isolation(manifest)
    if reason is not None:
        return {"status": "blocked", "reason_code": reason}
    if not config.soundfont.is_file() or not config.fluidsynth.is_file():
        return {"status": "blocked", "reason_code": "full_mix_augmentation_renderer_unavailable"}
    output_dir = config.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = _select_items(manifest, "train", config.max_train_items) + _select_items(
        manifest, "validation", config.max_validation_items
    )
    if not selected:
        return {"status": "blocked", "reason_code": "full_mix_augmentation_source_missing"}
    separator = DemucsSourceSeparator(device=config.demucs_device)
    augmented: list[dict[str, Any]] = []
    for index, item in enumerate(selected):
        result = _augment_item(item, output_dir / "items" / f"{index:03d}", config, separator, runner)
        if result is not None:
            augmented.append(result)
    if not augmented:
        return {"status": "blocked", "reason_code": "full_mix_augmentation_demucs_failed"}
    payload = {
        "schema_version": "1.0",
        "status": "completed",
        "training_kind": "source_isolated_gmd_synthetic_full_mix_demucs_stems",
        "training_source_ids": manifest["training_source_ids"],
        "validation_source_ids": manifest["validation_source_ids"],
        "benchmark_source_ids": manifest["benchmark_source_ids"],
        "source_id_overlap_with_benchmark": False,
        "items": augmented,
    }
    manifest_path = output_dir / "augmentation_manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "completed", "manifest_path": manifest_path, "item_count": len(augmented)}


def _select_items(manifest: dict[str, Any], split: str, limit: int) -> list[dict[str, Any]]:
    allowed = set(manifest["training_source_ids"] if split == "train" else manifest["validation_source_ids"])
    result = []
    for item in manifest.get("items", []):
        if not isinstance(item, dict) or item.get("split") != split or item.get("source_id") not in allowed:
            continue
        if Path(str(item.get("audio_path") or "")).is_file() and Path(str(item.get("ground_truth_midi_path") or "")).is_file():
            result.append(item)
        if len(result) >= max(0, limit):
            break
    return result


def _augment_item(
    item: dict[str, Any],
    output_dir: Path,
    config: argparse.Namespace,
    separator: DemucsSourceSeparator,
    runner,
) -> dict[str, Any] | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    drums, _ = librosa.load(Path(str(item["audio_path"])), sr=_SAMPLE_RATE, mono=True)
    if drums.size == 0:
        return None
    duration = len(drums) / _SAMPLE_RATE
    tempo_bpm = float(item.get("tempo_bpm") or 120.0)
    backing_midi = output_dir / "backing.mid"
    backing_wav = output_dir / "backing.wav"
    mix_wav = output_dir / "mixture.wav"
    _write_backing_midi(backing_midi, duration_seconds=duration, tempo_bpm=tempo_bpm)
    completed = runner(
        [str(config.fluidsynth), "-ni", "-F", str(backing_wav), "-r", str(_SAMPLE_RATE), str(config.soundfont), str(backing_midi)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not backing_wav.is_file():
        return None
    backing, _ = librosa.load(backing_wav, sr=_SAMPLE_RATE, mono=True)
    length = min(len(drums), len(backing))
    if length <= 0:
        return None
    mixed = _mix(drums[:length], backing[:length])
    sf.write(mix_wav, mixed, _SAMPLE_RATE, subtype="PCM_16")
    try:
        stem = separator.separate(mix_wav, output_dir / "separation")
    except Exception:
        return None
    return {
        "id": f"augmented-{_safe_id(item.get('id'))}",
        "split": str(item["split"]),
        "source_id": str(item["source_id"]),
        "audio_path": str(stem.drums_path),
        "ground_truth_midi_path": str(item["ground_truth_midi_path"]),
        "tempo_bpm": tempo_bpm,
        "input_type": "synthetic_full_mix_training",
        "synthetic_full_mix": True,
        "real_audio_verified": False,
    }


def _write_backing_midi(path: Path, *, duration_seconds: float, tempo_bpm: float) -> None:
    ticks_per_beat = 480
    beat_count = max(4, math.ceil(duration_seconds * tempo_bpm / 60.0))
    midi = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    piano = mido.MidiTrack()
    bass = mido.MidiTrack()
    midi.tracks.extend([piano, bass])
    tempo = mido.bpm2tempo(tempo_bpm)
    for track, program in ((piano, 4), (bass, 33)):
        track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
        track.append(mido.Message("program_change", program=program, channel=0 if track is piano else 1, time=0))
    chord_cycle = ((60, 64, 67), (57, 60, 64), (53, 57, 60), (55, 59, 62))
    for beat in range(0, beat_count, 4):
        chord = chord_cycle[(beat // 4) % len(chord_cycle)]
        piano.append(mido.Message("note_on", note=chord[0], velocity=52, channel=0, time=0))
        for note in chord[1:]:
            piano.append(mido.Message("note_on", note=note, velocity=44, channel=0, time=0))
        piano.append(mido.Message("note_off", note=chord[0], velocity=0, channel=0, time=ticks_per_beat * 4 - 1))
        for note in chord[1:]:
            piano.append(mido.Message("note_off", note=note, velocity=0, channel=0, time=0))
    for beat in range(beat_count):
        note = (36, 33, 29, 31)[(beat // 4) % 4]
        bass.append(mido.Message("note_on", note=note, velocity=60, channel=1, time=0))
        bass.append(mido.Message("note_off", note=note, velocity=0, channel=1, time=ticks_per_beat - 1))
    midi.save(path)


def _mix(drums: np.ndarray, backing: np.ndarray) -> np.ndarray:
    drum_peak = max(float(np.max(np.abs(drums))), 1e-4)
    backing_peak = max(float(np.max(np.abs(backing))), 1e-4)
    mixed = drums / drum_peak * 0.78 + backing / backing_peak * 0.28
    return np.clip(mixed, -0.98, 0.98).astype(np.float32)


def _validate_source_isolation(manifest: dict[str, Any]) -> str | None:
    required = ("training_source_ids", "validation_source_ids", "benchmark_source_ids", "items")
    if any(key not in manifest for key in required):
        return "training_manifest_invalid"
    train = {str(value) for value in manifest["training_source_ids"]}
    validation = {str(value) for value in manifest["validation_source_ids"]}
    benchmark = {str(value) for value in manifest["benchmark_source_ids"]}
    if not train or not validation or train & validation or (train | validation) & benchmark:
        return "training_source_id_isolation_invalid"
    return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_id(value: object) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in str(value or "item"))[:80]


if __name__ == "__main__":
    report = build(parse_args())
    print(json.dumps({"status": report["status"], "reason_code": report.get("reason_code"), "item_count": report.get("item_count")}, ensure_ascii=False))
