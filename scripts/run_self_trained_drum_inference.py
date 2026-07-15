from __future__ import annotations

import argparse
from pathlib import Path

import librosa
import numpy as np

from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent


_NOTES = {"kick": 36, "snare": 38, "closed_hat": 42, "open_hat": 46, "tom": 45, "cymbal": 49}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the private self-trained drum prototype model.")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tempo-bpm", type=float, required=True)
    return parser.parse_args()


def infer(config: argparse.Namespace) -> int:
    payload = np.load(config.model, allow_pickle=False)
    classes = [str(value) for value in payload["classes"]]
    centroids = np.asarray(payload["centroids"], dtype=np.float32)
    sample_rate = int(payload["sample_rate"])
    n_mels = int(payload["n_mels"])
    audio, _ = librosa.load(config.input, sr=sample_rate, mono=True)
    hop_length = 256
    onsets = librosa.onset.onset_detect(y=audio, sr=sample_rate, hop_length=hop_length, units="frames")
    mel = librosa.feature.melspectrogram(y=audio, sr=sample_rate, n_mels=n_mels, hop_length=hop_length, power=2.0)
    db = librosa.power_to_db(mel, ref=np.max)
    events = []
    for frame in onsets:
        index = min(int(frame), db.shape[1] - 1)
        feature = np.mean(db[:, index : min(db.shape[1], index + 4)], axis=1).astype(np.float32)
        distances = np.mean((centroids - feature) ** 2, axis=1)
        drum = classes[int(np.argmin(distances))]
        if drum not in _NOTES:
            continue
        seconds = librosa.frames_to_time(index, sr=sample_rate, hop_length=hop_length)
        tick = round(float(seconds) * config.tempo_bpm / 60.0 * 480)
        events.append(ProcessedDrumEvent(tick=max(0, tick), note=_NOTES[drum], drum=drum, velocity=96))
    write_drum_midi(config.output, tuple(events), ticks_per_beat=480, tempo_bpm=config.tempo_bpm)
    return 0


if __name__ == "__main__":
    raise SystemExit(infer(parse_args()))
