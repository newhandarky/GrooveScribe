from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import librosa
import numpy as np

from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.simple_midi import parse_midi
from ai_pipeline.midi.types import ProcessedDrumEvent


_DRUM_NOTES = {
    "kick": 36,
    "snare": 38,
    "closed_hat": 42,
    "open_hat": 46,
    "tom": 45,
    "cymbal": 49,
}
_SAMPLE_RATE = 22_050
_N_MELS = 64
_TRAINING_SOURCE_IDS = ("synthetic_generaluser_train_a", "synthetic_generaluser_train_b")
_VALIDATION_SOURCE_IDS = ("synthetic_generaluser_validation",)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a repo-external, synthetic multi-class drum prototype baseline.")
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--soundfont", type=Path, default=None, help="Required only for the synthetic fallback.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fluidsynth", type=Path, default=Path("fluidsynth"))
    parser.add_argument("--max-samples-per-class", type=int, default=800)
    return parser.parse_args()


def train(config: argparse.Namespace, *, runner=subprocess.run) -> dict:
    output_dir = config.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(getattr(config, "manifest", None))
    if manifest is not None:
        features, metadata = _features_from_manifest(manifest, max_samples_per_class=config.max_samples_per_class)
        if metadata.get("reason_code"):
            return {"status": "blocked", "reason_code": metadata["reason_code"]}
    else:
        if config.soundfont is None or not config.soundfont.is_file():
            return {"status": "blocked", "reason_code": "synthetic_renderer_soundfont_missing"}
        features = _synthetic_features(config, output_dir, runner)
        if features is None:
            return {"status": "blocked", "reason_code": "synthetic_renderer_failed"}
        metadata = {
            "training_kind": "synthetic_isolated_drum_hits",
            "training_source_ids": list(_TRAINING_SOURCE_IDS),
            "validation_source_ids": list(_VALIDATION_SOURCE_IDS),
            "source_id_overlap_with_benchmark": False,
        }
    if any(not values for values in features.values()):
        return {"status": "blocked", "reason_code": "multiclass_training_labels_insufficient"}

    classes = tuple(_DRUM_NOTES)
    centroids = np.stack([np.mean(features[drum], axis=0) for drum in classes])
    model_path = output_dir / "self_trained_drum_prototype_v1.npz"
    np.savez(model_path, classes=np.asarray(classes), centroids=centroids, sample_rate=_SAMPLE_RATE, n_mels=_N_MELS)
    metadata = {
        "schema_version": "1.0",
        "status": "completed",
        "model": "groovescribe_self_trained_prototype_v1",
        "training_kind": metadata["training_kind"],
        "classes": list(classes),
        "training_source_ids": metadata["training_source_ids"],
        "validation_source_ids": metadata["validation_source_ids"],
        "benchmark_source_ids": metadata.get("benchmark_source_ids", []),
        "source_id_overlap_with_benchmark": metadata["source_id_overlap_with_benchmark"],
        "sample_count_by_class": {drum: len(values) for drum, values in features.items()},
        "model_file": model_path.name,
        "limitations": [
            "Synthetic isolated-hit training is a reproducible baseline, not production-quality evidence.",
            "This model must pass external ground-truth benchmarks before any product integration.",
        ],
    }
    (output_dir / "training_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {"status": "completed", "model_path": model_path, "metadata_path": output_dir / "training_metadata.json"}


def _features_from_manifest(manifest: dict[str, Any], *, max_samples_per_class: int) -> tuple[dict[str, list[np.ndarray]], dict[str, Any]]:
    items = manifest.get("items") if isinstance(manifest.get("items"), list) else []
    train_sources = {str(value) for value in manifest.get("training_source_ids", []) if isinstance(value, str)}
    validation_sources = {str(value) for value in manifest.get("validation_source_ids", []) if isinstance(value, str)}
    benchmark_sources = {str(value) for value in manifest.get("benchmark_source_ids", []) if isinstance(value, str)}
    if not train_sources or not validation_sources or train_sources & validation_sources or (train_sources | validation_sources) & benchmark_sources:
        return {}, {"reason_code": "training_source_id_isolation_invalid"}
    features: dict[str, list[np.ndarray]] = {drum: [] for drum in _DRUM_NOTES}
    for item in items:
        if not isinstance(item, dict) or item.get("split") != "train":
            continue
        if str(item.get("source_id") or "") not in train_sources:
            return {}, {"reason_code": "training_source_id_isolation_invalid"}
        audio_path = Path(str(item.get("audio_path") or ""))
        midi_path = Path(str(item.get("ground_truth_midi_path") or ""))
        tempo_bpm = item.get("tempo_bpm")
        if not audio_path.is_file() or not midi_path.is_file() or not isinstance(tempo_bpm, (int, float)):
            continue
        audio, sample_rate = librosa.load(audio_path, sr=_SAMPLE_RATE, mono=True)
        mel = librosa.feature.melspectrogram(y=audio, sr=sample_rate, n_mels=_N_MELS, hop_length=256, power=2.0)
        db = librosa.power_to_db(mel, ref=np.max)
        parsed = parse_midi(midi_path)
        for note in parsed.notes:
            mapping = map_to_general_midi_drum(note.note)
            drum = "closed_hat" if mapping is not None and mapping.drum == "pedal_hat" else (mapping.drum if mapping else None)
            if drum not in features or len(features[drum]) >= max_samples_per_class:
                continue
            onset_seconds = note.tick / max(1, parsed.ticks_per_beat) * 60.0 / float(tempo_bpm)
            features[drum].append(_feature_from_db(db, onset_seconds=onset_seconds, sample_rate=sample_rate))
    return features, {
        "training_kind": "gmd_recordings_with_aligned_midi",
        "training_source_ids": sorted(train_sources),
        "validation_source_ids": sorted(validation_sources),
        "benchmark_source_ids": sorted(benchmark_sources),
        "source_id_overlap_with_benchmark": False,
    }


def _synthetic_features(config: argparse.Namespace, output_dir: Path, runner) -> dict[str, list[np.ndarray]] | None:
    features: dict[str, list[np.ndarray]] = {drum: [] for drum in _DRUM_NOTES}
    for drum, note in _DRUM_NOTES.items():
        for velocity in (64, 96, 120):
            midi = output_dir / "training-audio" / f"{drum}-{velocity}.mid"
            wav = midi.with_suffix(".wav")
            write_drum_midi(midi, (ProcessedDrumEvent(tick=960, note=note, drum=drum, velocity=velocity),), ticks_per_beat=480, tempo_bpm=120.0)
            command = [str(config.fluidsynth), "-ni", "-F", str(wav), "-r", "44100", str(config.soundfont), str(midi)]
            try:
                completed = runner(command, capture_output=True, text=True, check=False)
            except FileNotFoundError:
                return None
            if completed.returncode != 0 or not wav.is_file():
                return None
            features[drum].append(_feature(wav, onset_seconds=1.0))
    return features


def _feature(path: Path, *, onset_seconds: float) -> np.ndarray:
    audio, sample_rate = librosa.load(path, sr=_SAMPLE_RATE, mono=True)
    mel = librosa.feature.melspectrogram(y=audio, sr=sample_rate, n_mels=_N_MELS, hop_length=256, power=2.0)
    db = librosa.power_to_db(mel, ref=np.max)
    return _feature_from_db(db, onset_seconds=onset_seconds, sample_rate=sample_rate)


def _feature_from_db(db: np.ndarray, *, onset_seconds: float, sample_rate: int) -> np.ndarray:
    frame = min(max(0, round(onset_seconds * sample_rate / 256)), db.shape[1] - 1)
    window = db[:, frame : min(db.shape[1], frame + 4)]
    return np.mean(window, axis=1).astype(np.float32)


def _load_manifest(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


if __name__ == "__main__":
    report = train(parse_args())
    print(json.dumps({"status": report["status"], "reason_code": report.get("reason_code")}, ensure_ascii=False))
