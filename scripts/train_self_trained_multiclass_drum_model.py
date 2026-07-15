from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import torch
from torch import nn

from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.simple_midi import parse_midi


_CLASSES = ("kick", "snare", "closed_hat", "open_hat", "tom", "cymbal")
_SAMPLE_RATE = 22_050
_N_MELS = 64
_WINDOW_FRAMES = 5


class DrumFrameClassifier(nn.Module):
    def __init__(self, input_size: int, class_count: int) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_size, 192),
            nn.ReLU(),
            nn.Linear(192, 96),
            nn.ReLU(),
            nn.Linear(96, class_count),
        )

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        return self.layers(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a private source-isolated multi-class GMD drum classifier.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-samples-per-class", type=int, default=1_200)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    return parser.parse_args()


def train(config: argparse.Namespace) -> dict[str, Any]:
    manifest = _load_json(config.manifest)
    isolation = _validate_isolation(manifest)
    if isolation is not None:
        return {"status": "blocked", "reason_code": isolation}
    torch.manual_seed(config.seed)
    np.random.seed(config.seed)
    train_x, train_y = _dataset(manifest, split="train", max_samples_per_class=config.max_samples_per_class)
    validation_x, validation_y = _dataset(manifest, split="validation", max_samples_per_class=max(100, config.max_samples_per_class // 4))
    if train_x is None or validation_x is None:
        return {"status": "blocked", "reason_code": "multiclass_training_labels_insufficient"}
    mean = train_x.mean(axis=0, keepdims=True)
    std = np.maximum(train_x.std(axis=0, keepdims=True), 1e-4)
    train_tensor = torch.from_numpy((train_x - mean) / std)
    label_tensor = torch.from_numpy(train_y)
    model = DrumFrameClassifier(train_tensor.shape[1], len(_CLASSES))
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.CrossEntropyLoss()
    for _ in range(config.epochs):
        order = torch.randperm(len(train_tensor))
        for indices in order.split(128):
            optimizer.zero_grad()
            loss = loss_fn(model(train_tensor[indices]), label_tensor[indices])
            loss.backward()
            optimizer.step()
    with torch.no_grad():
        validation_tensor = torch.from_numpy((validation_x - mean) / std)
        predicted = model(validation_tensor).argmax(dim=1).numpy()
    validation_accuracy = float((predicted == validation_y).mean())
    output_dir = config.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "self_trained_multiclass_drum_v1.pt"
    torch.save(
        {
            "state_dict": model.state_dict(),
            "classes": _CLASSES,
            "input_size": int(train_tensor.shape[1]),
            "sample_rate": _SAMPLE_RATE,
            "n_mels": _N_MELS,
            "window_frames": _WINDOW_FRAMES,
            # Keep the checkpoint compatible with torch.load(weights_only=True).
            "mean": torch.from_numpy(mean.squeeze(0).copy()),
            "std": torch.from_numpy(std.squeeze(0).copy()),
        },
        model_path,
    )
    metadata = {
        "schema_version": "1.0",
        "status": "completed",
        "model": "groovescribe_self_trained_multiclass_v1",
        "training_kind": "gmd_recordings_with_aligned_midi_frame_classifier",
        "classes": list(_CLASSES),
        "training_source_ids": manifest["training_source_ids"],
        "validation_source_ids": manifest["validation_source_ids"],
        "benchmark_source_ids": manifest["benchmark_source_ids"],
        "source_id_overlap_with_benchmark": False,
        "train_sample_count": int(len(train_y)),
        "validation_sample_count": int(len(validation_y)),
        "validation_classification_accuracy": round(validation_accuracy, 4),
        "model_file": model_path.name,
    }
    (output_dir / "training_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "completed", "model_path": model_path, "metadata_path": output_dir / "training_metadata.json"}


def _dataset(manifest: dict[str, Any], *, split: str, max_samples_per_class: int) -> tuple[np.ndarray | None, np.ndarray | None]:
    features: dict[str, list[np.ndarray]] = {drum: [] for drum in _CLASSES}
    allowed = set(manifest["training_source_ids"] if split == "train" else manifest["validation_source_ids"])
    for item in manifest.get("items", []):
        if not isinstance(item, dict) or item.get("split") != split or item.get("source_id") not in allowed:
            continue
        audio_path = Path(str(item.get("audio_path") or ""))
        midi_path = Path(str(item.get("ground_truth_midi_path") or ""))
        tempo_bpm = item.get("tempo_bpm")
        if not audio_path.is_file() or not midi_path.is_file() or not isinstance(tempo_bpm, (int, float)):
            continue
        audio, sample_rate = librosa.load(audio_path, sr=_SAMPLE_RATE, mono=True)
        mel = librosa.feature.melspectrogram(y=audio, sr=sample_rate, n_mels=_N_MELS, hop_length=256, power=2.0)
        db = librosa.power_to_db(mel, ref=np.max)
        midi = parse_midi(midi_path)
        for note in midi.notes:
            mapping = map_to_general_midi_drum(note.note)
            drum = "closed_hat" if mapping is not None and mapping.drum == "pedal_hat" else (mapping.drum if mapping else None)
            if drum not in features or len(features[drum]) >= max_samples_per_class:
                continue
            seconds = note.tick / max(1, midi.ticks_per_beat) * 60.0 / float(tempo_bpm)
            features[drum].append(_feature_window(db, seconds=seconds, sample_rate=sample_rate))
    if any(not features[drum] for drum in _CLASSES):
        return None, None
    values = []
    labels = []
    for label, drum in enumerate(_CLASSES):
        values.extend(features[drum])
        labels.extend([label] * len(features[drum]))
    return np.stack(values).astype(np.float32), np.asarray(labels, dtype=np.int64)


def _feature_window(db: np.ndarray, *, seconds: float, sample_rate: int) -> np.ndarray:
    center = min(max(0, round(seconds * sample_rate / 256)), db.shape[1] - 1)
    start = max(0, center - 1)
    end = min(db.shape[1], start + _WINDOW_FRAMES)
    window = db[:, start:end]
    if window.shape[1] < _WINDOW_FRAMES:
        window = np.pad(window, ((0, 0), (0, _WINDOW_FRAMES - window.shape[1])), mode="edge")
    return window.reshape(-1).astype(np.float32)


def _validate_isolation(manifest: dict[str, Any]) -> str | None:
    required = ("training_source_ids", "validation_source_ids", "benchmark_source_ids", "items")
    if any(key not in manifest for key in required):
        return "training_manifest_invalid"
    train = {str(value) for value in manifest["training_source_ids"]}
    validation = {str(value) for value in manifest["validation_source_ids"]}
    benchmark = {str(value) for value in manifest["benchmark_source_ids"]}
    if not train or not validation or train & validation or (train | validation) & benchmark:
        return "training_source_id_isolation_invalid"
    return None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    report = train(parse_args())
    print(json.dumps({"status": report["status"], "reason_code": report.get("reason_code")}, ensure_ascii=False))
