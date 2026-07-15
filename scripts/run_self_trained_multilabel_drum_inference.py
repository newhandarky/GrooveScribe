from __future__ import annotations

import argparse
from pathlib import Path

import librosa
import numpy as np
import torch

from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent
from train_self_trained_multilabel_drum_model import DrumFrameMultiLabelClassifier


_NOTES = {"kick": 36, "snare": 38, "closed_hat": 42, "open_hat": 46, "tom": 45, "cymbal": 49}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the private multi-label GMD drum baseline.")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tempo-bpm", type=float, required=True)
    return parser.parse_args()


def infer(config: argparse.Namespace) -> int:
    payload = torch.load(config.model, map_location="cpu", weights_only=True)
    classes = [str(value) for value in payload["classes"]]
    model = DrumFrameMultiLabelClassifier(int(payload["input_size"]), len(classes))
    model.load_state_dict(payload["state_dict"])
    model.eval()
    sample_rate = int(payload["sample_rate"])
    n_mels = int(payload["n_mels"])
    hop_length = int(payload["hop_length"])
    window_frames = int(payload["window_frames"])
    mean = payload["mean"].detach().cpu().numpy().astype(np.float32)
    std = np.maximum(payload["std"].detach().cpu().numpy().astype(np.float32), 1e-4)
    thresholds = payload["thresholds"].detach().cpu().numpy().astype(np.float32)
    audio, _ = librosa.load(config.input, sr=sample_rate, mono=True)
    mel = librosa.feature.melspectrogram(y=audio, sr=sample_rate, n_mels=n_mels, hop_length=hop_length, power=2.0)
    db = librosa.power_to_db(mel, ref=np.max)
    features = np.stack([_feature_window(db, frame, window_frames) for frame in range(db.shape[1])]).astype(np.float32)
    probabilities = []
    with torch.no_grad():
        for batch in np.array_split(features, max(1, int(np.ceil(len(features) / 512)))):
            probabilities.append(torch.sigmoid(model(torch.from_numpy((batch - mean) / std))).numpy())
    scores = np.concatenate(probabilities, axis=0) if probabilities else np.empty((0, len(classes)), dtype=np.float32)
    events = []
    for class_index, drum in enumerate(classes):
        if drum not in _NOTES:
            continue
        for frame in _nms_frames(scores[:, class_index], float(thresholds[class_index]), radius_frames=3):
            seconds = librosa.frames_to_time(frame, sr=sample_rate, hop_length=hop_length)
            tick = round(float(seconds) * config.tempo_bpm / 60.0 * 480)
            velocity = max(36, min(127, round(float(scores[frame, class_index]) * 127)))
            events.append(ProcessedDrumEvent(tick=max(0, tick), note=_NOTES[drum], drum=drum, velocity=velocity))
    events.sort(key=lambda event: (event.tick, event.note))
    write_drum_midi(config.output, tuple(events), ticks_per_beat=480, tempo_bpm=config.tempo_bpm)
    return 0


def _feature_window(db: np.ndarray, center: int, window_frames: int) -> np.ndarray:
    start = max(0, min(center - 1, db.shape[1] - 1))
    window = db[:, start : min(db.shape[1], start + window_frames)]
    if window.shape[1] < window_frames:
        window = np.pad(window, ((0, 0), (0, window_frames - window.shape[1])), mode="edge")
    return window.reshape(-1).astype(np.float32)


def _nms_frames(scores: np.ndarray, threshold: float, *, radius_frames: int) -> list[int]:
    candidates = [int(frame) for frame in np.flatnonzero(scores >= threshold)]
    selected: list[int] = []
    for frame in sorted(candidates, key=lambda item: (-float(scores[item]), item)):
        if all(abs(frame - kept) > radius_frames for kept in selected):
            selected.append(frame)
    return sorted(selected)


if __name__ == "__main__":
    raise SystemExit(infer(parse_args()))
