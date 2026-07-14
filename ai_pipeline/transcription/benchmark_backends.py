from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent


@dataclass(frozen=True)
class BackendAvailability:
    backend: str
    ready: bool
    reason_code: str | None = None


class SpectralOnsetDrumBackend:
    """A benchmark-only, dependency-light drum onset baseline using librosa."""

    name = "spectral_onset_spike"

    def availability(self) -> BackendAvailability:
        try:
            import librosa  # noqa: F401
            import numpy  # noqa: F401
        except ImportError:
            return BackendAvailability(self.name, False, "librosa_runtime_unavailable")
        return BackendAvailability(self.name, True)

    def transcribe(self, drums_stem: Path, output_midi: Path, *, tempo_bpm: float) -> dict:
        availability = self.availability()
        if not availability.ready:
            return {"status": "blocked", "backend": self.name, "reason_code": availability.reason_code}
        import librosa
        import numpy as np

        audio, sample_rate = librosa.load(str(drums_stem), sr=None, mono=True)
        hop_length = 512
        onset_frames = librosa.onset.onset_detect(y=audio, sr=sample_rate, hop_length=hop_length, units="frames")
        stft = np.abs(librosa.stft(audio, hop_length=hop_length))
        frequencies = librosa.fft_frequencies(sr=sample_rate)
        events = []
        for frame in onset_frames:
            index = min(int(frame), stft.shape[1] - 1)
            spectrum = stft[:, index]
            drum = _classify_spectrum(spectrum, frequencies)
            seconds = librosa.frames_to_time(index, sr=sample_rate, hop_length=hop_length)
            tick = round(float(seconds) * tempo_bpm / 60.0 * 480)
            note = {"kick": 36, "snare": 38, "closed_hat": 42}[drum]
            events.append(ProcessedDrumEvent(tick=max(0, tick), note=note, drum=drum, velocity=96))
        write_drum_midi(output_midi, tuple(events), ticks_per_beat=480, tempo_bpm=tempo_bpm)
        return {"status": "completed", "backend": self.name, "event_count": len(events)}


def get_benchmark_backend(name: str) -> SpectralOnsetDrumBackend | None:
    return SpectralOnsetDrumBackend() if name == SpectralOnsetDrumBackend.name else None


def _classify_spectrum(spectrum, frequencies) -> str:
    def energy(low: float, high: float) -> float:
        mask = (frequencies >= low) & (frequencies < high)
        return float(spectrum[mask].mean()) if mask.any() else 0.0

    kick = energy(30, 180) * 1.5
    snare = energy(180, 4_000)
    hat = energy(5_000, 14_000) * 1.2
    return max(((kick, "kick"), (snare, "snare"), (hat, "closed_hat")), key=lambda item: item[0])[1]
