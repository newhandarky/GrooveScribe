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
_HOP_LENGTH = 256
_WINDOW_FRAMES = 5


class DrumFrameMultiLabelClassifier(nn.Module):
    def __init__(self, input_size: int, class_count: int) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_size, 256),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, class_count),
        )

    def forward(self, value: torch.Tensor) -> torch.Tensor:
        return self.layers(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a private source-isolated multi-label GMD drum frame baseline.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--augmentation-manifest", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-frames-per-item", type=int, default=2_000)
    parser.add_argument("--epochs", type=int, default=24)
    parser.add_argument("--seed", type=int, default=11)
    return parser.parse_args()


def train(config: argparse.Namespace) -> dict[str, Any]:
    manifest = _load_json(config.manifest)
    isolation = _validate_isolation(manifest)
    if isolation is not None:
        return {"status": "blocked", "reason_code": isolation}
    augmentation = _load_json(config.augmentation_manifest) if config.augmentation_manifest else None
    if augmentation is not None:
        augmentation_isolation = _validate_augmentation(augmentation, manifest)
        if augmentation_isolation is not None:
            return {"status": "blocked", "reason_code": augmentation_isolation}
        manifest = {**manifest, "items": [*manifest["items"], *augmentation["items"]]}
    torch.manual_seed(config.seed)
    np.random.seed(config.seed)
    train_x, train_y = _dataset(manifest, split="train", max_frames_per_item=config.max_frames_per_item, seed=config.seed)
    validation_x, validation_y = _dataset(
        manifest,
        split="validation",
        max_frames_per_item=config.max_frames_per_item,
        seed=config.seed + 1,
    )
    if train_x is None or validation_x is None:
        return {"status": "blocked", "reason_code": "multilabel_training_labels_insufficient"}

    mean = train_x.mean(axis=0, keepdims=True)
    std = np.maximum(train_x.std(axis=0, keepdims=True), 1e-4)
    train_tensor = torch.from_numpy((train_x - mean) / std)
    target_tensor = torch.from_numpy(train_y)
    positives = target_tensor.sum(dim=0)
    pos_weight = torch.clamp((len(target_tensor) - positives) / torch.clamp(positives, min=1), max=20.0)
    model = DrumFrameMultiLabelClassifier(train_tensor.shape[1], len(_CLASSES))
    optimizer = torch.optim.Adam(model.parameters(), lr=8e-4)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    for _ in range(config.epochs):
        order = torch.randperm(len(train_tensor))
        for indices in order.split(256):
            optimizer.zero_grad()
            loss = loss_fn(model(train_tensor[indices]), target_tensor[indices])
            loss.backward()
            optimizer.step()

    with torch.no_grad():
        validation_tensor = torch.from_numpy((validation_x - mean) / std)
        probabilities = torch.sigmoid(model(validation_tensor)).numpy()
    thresholds, validation_f1 = _calibrate_thresholds(probabilities, validation_y)
    output_dir = config.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "self_trained_multilabel_drum_v2.pt"
    torch.save(
        {
            "state_dict": model.state_dict(),
            "classes": _CLASSES,
            "input_size": int(train_tensor.shape[1]),
            "sample_rate": _SAMPLE_RATE,
            "n_mels": _N_MELS,
            "hop_length": _HOP_LENGTH,
            "window_frames": _WINDOW_FRAMES,
            "mean": torch.from_numpy(mean.squeeze(0).copy()),
            "std": torch.from_numpy(std.squeeze(0).copy()),
            "thresholds": torch.tensor(thresholds, dtype=torch.float32),
        },
        model_path,
    )
    metadata = {
        "schema_version": "1.0",
        "status": "completed",
        "model": "groovescribe_self_trained_multilabel_v2",
        "training_kind": "gmd_recordings_with_aligned_midi_multilabel_frame_classifier",
        "classes": list(_CLASSES),
        "training_source_ids": manifest["training_source_ids"],
        "validation_source_ids": manifest["validation_source_ids"],
        "benchmark_source_ids": manifest["benchmark_source_ids"],
        "source_id_overlap_with_benchmark": False,
        "train_frame_count": int(len(train_y)),
        "validation_frame_count": int(len(validation_y)),
        "validation_frame_f1_by_class": validation_f1,
        "inference_thresholds": {drum: round(float(threshold), 3) for drum, threshold in zip(_CLASSES, thresholds, strict=True)},
        "model_file": model_path.name,
        "augmentation_item_count": len(augmentation.get("items", [])) if augmentation else 0,
    }
    (output_dir / "training_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "completed", "model_path": model_path, "metadata_path": output_dir / "training_metadata.json"}


def _dataset(
    manifest: dict[str, Any],
    *,
    split: str,
    max_frames_per_item: int,
    seed: int,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    allowed = set(manifest["training_source_ids"] if split == "train" else manifest["validation_source_ids"])
    features: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    for item_index, item in enumerate(manifest.get("items", [])):
        if not isinstance(item, dict) or item.get("split") != split or item.get("source_id") not in allowed:
            continue
        audio_path = Path(str(item.get("audio_path") or ""))
        midi_path = Path(str(item.get("ground_truth_midi_path") or ""))
        tempo_bpm = item.get("tempo_bpm")
        if not audio_path.is_file() or not midi_path.is_file() or not isinstance(tempo_bpm, (int, float)):
            continue
        audio, _ = librosa.load(audio_path, sr=_SAMPLE_RATE, mono=True)
        mel = librosa.feature.melspectrogram(y=audio, sr=_SAMPLE_RATE, n_mels=_N_MELS, hop_length=_HOP_LENGTH, power=2.0)
        db = librosa.power_to_db(mel, ref=np.max)
        frame_labels = _frame_labels(parse_midi(midi_path), tempo_bpm=float(tempo_bpm), frame_count=db.shape[1])
        indices = _sample_indices(frame_labels, max_frames=max_frames_per_item, seed=seed + item_index)
        for frame in indices:
            features.append(_feature_window(db, frame))
            labels.append(frame_labels[frame])
    if not features or not labels or not any(np.any(row) for row in labels):
        return None, None
    return np.stack(features).astype(np.float32), np.stack(labels).astype(np.float32)


def _frame_labels(midi, *, tempo_bpm: float, frame_count: int) -> np.ndarray:
    labels = np.zeros((frame_count, len(_CLASSES)), dtype=np.float32)
    class_index = {drum: index for index, drum in enumerate(_CLASSES)}
    for note in midi.notes:
        mapping = map_to_general_midi_drum(note.note)
        drum = "closed_hat" if mapping is not None and mapping.drum == "pedal_hat" else (mapping.drum if mapping else None)
        if drum not in class_index:
            continue
        seconds = note.tick / max(1, midi.ticks_per_beat) * 60.0 / tempo_bpm
        center = min(max(0, round(seconds * _SAMPLE_RATE / _HOP_LENGTH)), frame_count - 1)
        labels[max(0, center - 1) : min(frame_count, center + 2), class_index[drum]] = 1.0
    return labels


def _sample_indices(labels: np.ndarray, *, max_frames: int, seed: int) -> np.ndarray:
    positives = np.flatnonzero(labels.any(axis=1))
    negatives = np.flatnonzero(~labels.any(axis=1))
    rng = np.random.default_rng(seed)
    negative_count = min(len(negatives), max(len(positives) * 2, 1))
    selected = np.concatenate((positives, rng.choice(negatives, size=negative_count, replace=False))) if len(negatives) else positives
    if len(selected) > max_frames:
        selected = rng.choice(selected, size=max_frames, replace=False)
    return np.sort(selected)


def _feature_window(db: np.ndarray, center: int) -> np.ndarray:
    start = max(0, min(center - 1, db.shape[1] - 1))
    window = db[:, start : min(db.shape[1], start + _WINDOW_FRAMES)]
    if window.shape[1] < _WINDOW_FRAMES:
        window = np.pad(window, ((0, 0), (0, _WINDOW_FRAMES - window.shape[1])), mode="edge")
    return window.reshape(-1).astype(np.float32)


def _calibrate_thresholds(probabilities: np.ndarray, labels: np.ndarray) -> tuple[list[float], dict[str, float]]:
    thresholds = []
    scores: dict[str, float] = {}
    for index, drum in enumerate(_CLASSES):
        best_threshold = 0.5
        best_score = -1.0
        truth = labels[:, index] > 0.5
        for threshold in np.arange(0.2, 0.81, 0.05):
            predicted = probabilities[:, index] >= threshold
            tp = int(np.logical_and(predicted, truth).sum())
            fp = int(np.logical_and(predicted, ~truth).sum())
            fn = int(np.logical_and(~predicted, truth).sum())
            score = 2 * tp / max(1, 2 * tp + fp + fn)
            if score > best_score:
                best_threshold, best_score = float(threshold), float(score)
        thresholds.append(best_threshold)
        scores[drum] = round(best_score, 4)
    return thresholds, scores


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


def _validate_augmentation(augmentation: dict[str, Any], source_manifest: dict[str, Any]) -> str | None:
    if augmentation.get("source_id_overlap_with_benchmark") is not False or not isinstance(augmentation.get("items"), list):
        return "training_augmentation_manifest_invalid"
    expected = {
        "training_source_ids": source_manifest["training_source_ids"],
        "validation_source_ids": source_manifest["validation_source_ids"],
        "benchmark_source_ids": source_manifest["benchmark_source_ids"],
    }
    if any(augmentation.get(key) != value for key, value in expected.items()):
        return "training_augmentation_source_id_isolation_invalid"
    allowed = set(expected["training_source_ids"]) | set(expected["validation_source_ids"])
    if any(not isinstance(item, dict) or item.get("source_id") not in allowed for item in augmentation["items"]):
        return "training_augmentation_source_id_isolation_invalid"
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
