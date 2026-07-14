from __future__ import annotations

import importlib.util
from pathlib import Path

from ai_pipeline.benchmark.metrics import compare_drum_midi, primary_failure_stage
from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent
from ai_pipeline.transcription.benchmark_backends import BackendAvailability, SpectralOnsetDrumBackend


def _midi(path: Path, events: tuple[ProcessedDrumEvent, ...]) -> Path:
    write_drum_midi(path, events, ticks_per_beat=480)
    return path


def test_stage_metrics_include_per_drum_false_positives_and_false_negatives(tmp_path: Path) -> None:
    ground_truth = _midi(
        tmp_path / "truth.mid",
        (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),),
    )
    predicted = _midi(
        tmp_path / "predicted.mid",
        (ProcessedDrumEvent(tick=0, note=38, drum="snare", velocity=100),),
    )

    metrics = compare_drum_midi(predicted, ground_truth)

    assert metrics["status"] == "measured"
    assert metrics["per_drum"]["kick"]["fn"] == 1
    assert metrics["per_drum"]["snare"]["fp"] == 1


def test_primary_failure_stage_distinguishes_postprocessor_and_chart_loss() -> None:
    assert primary_failure_stage({"raw": {"f1": 0.8}, "processed": {"f1": 0.6}, "chart": {"f1": 0.6}}) == "postprocessor"
    assert primary_failure_stage({"raw": {"f1": 0.8}, "processed": {"f1": 0.8}, "chart": {"f1": 0.6}}) == "chart_arranger"
    assert primary_failure_stage({"raw": {"f1": 0.2}, "processed": {"f1": 0.2}, "chart": {"f1": 0.2}}) == "demucs_or_raw_model"
    assert primary_failure_stage({"raw": {"f1": 0.2, "mean_timing_error_ticks": 80}, "processed": {"f1": 0.2}, "chart": {"f1": 0.2}}) == "timing_alignment"


def test_macro_f1_excludes_mutually_empty_drum_classes_but_penalizes_extra_tom(tmp_path: Path) -> None:
    truth = _midi(
        tmp_path / "truth.mid",
        (
            ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
            ProcessedDrumEvent(tick=240, note=42, drum="closed_hat", velocity=100),
            ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=100),
        ),
    )
    perfect = _midi(
        tmp_path / "perfect.mid",
        (
            ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
            ProcessedDrumEvent(tick=240, note=42, drum="closed_hat", velocity=100),
            ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=100),
        ),
    )
    extra_tom = _midi(
        tmp_path / "extra-tom.mid",
        (
            ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
            ProcessedDrumEvent(tick=240, note=42, drum="closed_hat", velocity=100),
            ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=100),
            ProcessedDrumEvent(tick=720, note=45, drum="tom", velocity=100),
        ),
    )

    assert compare_drum_midi(perfect, truth)["f1"] == 1.0
    assert compare_drum_midi(extra_tom, truth)["f1"] < 1.0


def test_alternative_backend_unknown_is_blocked_without_paths(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("alternative_spike", root / "scripts" / "run_alternative_drum_backend_spike.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    config = type("Config", (), {"backend": "missing", "output_dir": tmp_path, "manifest": tmp_path / "manifest.json", "adtof_benchmark_dir": tmp_path, "tom_filter_preset": None})()

    report = script.run_spike(config)

    assert report["status"] == "blocked"
    assert "/tmp/" not in (tmp_path / "alternative_backend_spike_report.json").read_text(encoding="utf-8")


def test_alternative_backend_runtime_unavailable_is_blocked(monkeypatch, tmp_path: Path) -> None:
    backend = SpectralOnsetDrumBackend()
    monkeypatch.setattr(backend, "availability", lambda: BackendAvailability(backend.name, False, "librosa_runtime_unavailable"))

    result = backend.transcribe(tmp_path / "drums.wav", tmp_path / "raw.mid", tempo_bpm=120.0)

    assert result == {"status": "blocked", "backend": "spectral_onset_spike", "reason_code": "librosa_runtime_unavailable"}


def test_alternative_candidate_rejects_core_false_positive_or_gate_regression(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("alternative_candidate", root / "scripts" / "run_alternative_drum_backend_spike.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    comparison = {
        input_type: {
            "chart_f1_delta": 0.1,
            "per_drum": {drum: {"delta": 0.1} for drum in ("kick", "snare", "closed_hat")},
            "core_groove_f1": {"alternative": 0.8, "adtof": 0.7},
            "core_fp_total": {"alternative": 11, "adtof": 10},
            "gate_verdicts": {"alternative": {}, "adtof": {}},
        }
        for input_type in ("drum_only", "full_mix")
    }

    assert script._is_integration_candidate([{"status": "completed"}], comparison) is False


def test_error_breakdown_skips_unverified_provenance(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("breakdown", root / "scripts" / "run_performance_error_breakdown.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    ground_truth = _midi(tmp_path / "truth.mid", (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),))

    result = script._item_breakdown({"id": "unsafe", "audio_path": str(audio), "ground_truth_midi_path": str(ground_truth)}, tmp_path)

    assert result["status"] == "skipped"
    assert result["reason"] == "benchmark_provenance_invalid"
