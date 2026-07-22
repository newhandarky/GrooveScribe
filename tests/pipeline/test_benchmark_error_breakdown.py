from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from ai_pipeline.benchmark.metrics import audit_drum_midi_contract, compare_drum_midi, primary_failure_stage
from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent
from ai_pipeline.transcription.benchmark_backends import (
    BackendAvailability,
    MagentaOnsetsFramesDrumBackend,
    SelfTrainedMultilabelDrumBackend,
    SelfTrainedMulticlassDrumBackend,
    SelfTrainedPrototypeDrumBackend,
    SpectralOnsetDrumBackend,
)


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


def test_benchmark_taxonomy_normalizes_pedal_hat_and_preserves_source_counts(tmp_path: Path) -> None:
    truth = _midi(
        tmp_path / "truth.mid",
        (ProcessedDrumEvent(tick=0, note=44, drum="pedal_hat", velocity=100),),
    )
    predicted = _midi(
        tmp_path / "predicted.mid",
        (ProcessedDrumEvent(tick=0, note=42, drum="closed_hat", velocity=100),),
    )

    metrics = compare_drum_midi(predicted, truth)

    assert metrics["per_drum"]["closed_hat"]["tp"] == 1
    assert metrics["taxonomy"]["ground_truth_source_counts"] == {"pedal_hat": 1}
    assert metrics["confusion_matrix"]["closed_hat"]["closed_hat"] == 1


def test_contract_audit_reports_bounded_global_offset_without_changing_uncorrected_score(tmp_path: Path) -> None:
    truth = _midi(
        tmp_path / "truth.mid",
        (ProcessedDrumEvent(tick=120, note=36, drum="kick", velocity=100),),
    )
    predicted = _midi(
        tmp_path / "predicted.mid",
        (ProcessedDrumEvent(tick=200, note=36, drum="kick", velocity=100),),
    )

    audit = audit_drum_midi_contract(predicted, truth)

    assert audit["status"] == "measured"
    assert audit["uncorrected"]["per_drum"]["kick"]["tp"] == 0
    assert audit["offset_corrected"]["per_drum"]["kick"]["tp"] == 1
    assert audit["global_timing_offset"]["best_offset_ticks"] == -80
    assert audit["global_timing_offset"]["max_abs_offset_ticks"] == 120


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


def test_pretrained_magenta_backend_is_blocked_without_private_runtime_template(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GROOVESCRIBE_MAGENTA_DRUM_COMMAND_TEMPLATE", raising=False)
    backend = MagentaOnsetsFramesDrumBackend()

    assert backend.availability() == BackendAvailability(
        "magenta_onsets_frames_drums",
        False,
        "magenta_onsets_frames_runtime_unavailable",
    )
    assert backend.transcribe(tmp_path / "drums.wav", tmp_path / "raw.mid", tempo_bpm=120.0) == {
        "status": "blocked",
        "backend": "magenta_onsets_frames_drums",
        "reason_code": "magenta_onsets_frames_runtime_unavailable",
    }


@pytest.mark.parametrize(
    ("template", "backend_type", "reason_code"),
    [
        ("/bin/echo --input {input} --output {output} --device {device}", MagentaOnsetsFramesDrumBackend, "magenta_onsets_frames_command_invalid"),
        ("/bin/echo --output {output}", MagentaOnsetsFramesDrumBackend, "magenta_onsets_frames_command_invalid"),
        ("/bin/echo --input {input}", MagentaOnsetsFramesDrumBackend, "magenta_onsets_frames_command_invalid"),
        ("/bin/echo --input {input", MagentaOnsetsFramesDrumBackend, "magenta_onsets_frames_command_invalid"),
        ("/bin/echo --input {input} --output {output} --device {device}", SelfTrainedPrototypeDrumBackend, "self_trained_prototype_command_invalid"),
        ("/bin/echo --output {output}", SelfTrainedPrototypeDrumBackend, "self_trained_prototype_command_invalid"),
        ("/bin/echo --input {input}", SelfTrainedPrototypeDrumBackend, "self_trained_prototype_command_invalid"),
        ("/bin/echo --input {input", SelfTrainedPrototypeDrumBackend, "self_trained_prototype_command_invalid"),
        ("/bin/echo --input {input} --output {output} --device {device}", SelfTrainedMulticlassDrumBackend, "self_trained_multiclass_command_invalid"),
        ("/bin/echo --output {output}", SelfTrainedMulticlassDrumBackend, "self_trained_multiclass_command_invalid"),
        ("/bin/echo --input {input}", SelfTrainedMulticlassDrumBackend, "self_trained_multiclass_command_invalid"),
        ("/bin/echo --input {input", SelfTrainedMulticlassDrumBackend, "self_trained_multiclass_command_invalid"),
        ("/bin/echo --input {input} --output {output} --device {device}", SelfTrainedMultilabelDrumBackend, "self_trained_multilabel_command_invalid"),
        ("/bin/echo --output {output}", SelfTrainedMultilabelDrumBackend, "self_trained_multilabel_command_invalid"),
        ("/bin/echo --input {input}", SelfTrainedMultilabelDrumBackend, "self_trained_multilabel_command_invalid"),
        ("/bin/echo --input {input", SelfTrainedMultilabelDrumBackend, "self_trained_multilabel_command_invalid"),
    ],
)
def test_template_backends_block_invalid_command_templates(template: str, backend_type, reason_code: str) -> None:
    backend = backend_type(command_template=template)

    assert backend.availability() == BackendAvailability(backend.name, False, reason_code)


def test_magenta_backend_defensively_blocks_template_format_error_after_availability(monkeypatch, tmp_path: Path) -> None:
    drums = tmp_path / "drums.wav"
    drums.write_bytes(b"audio")
    backend = MagentaOnsetsFramesDrumBackend(command_template="/bin/echo --input {input} --output {output} --device {device}")
    monkeypatch.setattr(backend, "availability", lambda: BackendAvailability(backend.name, True))

    result = backend.transcribe(drums, tmp_path / "raw.mid", tempo_bpm=120.0)

    assert result == {
        "status": "blocked",
        "backend": "magenta_onsets_frames_drums",
        "reason_code": "magenta_onsets_frames_command_invalid",
    }


@pytest.mark.parametrize(
    ("backend_type", "reason_code"),
    [
        (SelfTrainedPrototypeDrumBackend, "self_trained_prototype_command_invalid"),
        (SelfTrainedMulticlassDrumBackend, "self_trained_multiclass_command_invalid"),
        (SelfTrainedMultilabelDrumBackend, "self_trained_multilabel_command_invalid"),
    ],
)
def test_self_trained_backends_defensively_block_template_format_error_after_availability(
    monkeypatch,
    tmp_path: Path,
    backend_type,
    reason_code: str,
) -> None:
    drums = tmp_path / "drums.wav"
    drums.write_bytes(b"audio")
    backend = backend_type(command_template="/bin/echo --input {input} --output {output} --device {device}")
    monkeypatch.setattr(backend, "availability", lambda: BackendAvailability(backend.name, True))

    result = backend.transcribe(drums, tmp_path / "raw.mid", tempo_bpm=120.0)

    assert result == {
        "status": "blocked",
        "backend": backend.name,
        "reason_code": reason_code,
    }


def test_pretrained_backend_blocked_report_keeps_calibration_fail_closed(monkeypatch, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("alternative_magenta", root / "scripts" / "run_alternative_drum_backend_spike.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.delenv("GROOVESCRIBE_MAGENTA_DRUM_COMMAND_TEMPLATE", raising=False)
    (tmp_path / "gate_calibration.json").write_text('{"status":"insufficient_evidence","allow_performance_ready":false}', encoding="utf-8")
    config = type("Config", (), {"backend": "magenta_onsets_frames_drums", "output_dir": tmp_path / "output", "manifest": tmp_path / "manifest.json", "adtof_benchmark_dir": tmp_path, "tom_filter_preset": None})()

    report = script.run_spike(config)

    assert report["status"] == "blocked"
    assert report["integration_candidate"] is False
    assert report["calibration_audit"]["allow_performance_ready"] is False
    assert report["backend_provenance"] == {"model_source": "magenta_onsets_frames_e_gmd", "model_license": "Apache-2.0"}
    assert report["redaction"] == {"status": "passed", "unsafe_token_count": 0}


def test_pretrained_magenta_backend_requires_multiclass_standard_midi_output(tmp_path: Path) -> None:
    drums = tmp_path / "drums.wav"
    drums.write_bytes(b"audio")
    output = tmp_path / "raw.mid"

    def runner(command, **kwargs):
        output_path = Path(command[command.index("--output") + 1])
        write_drum_midi(
            output_path,
            (
                ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
                ProcessedDrumEvent(tick=240, note=38, drum="snare", velocity=100),
            ),
            ticks_per_beat=480,
        )
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    backend = MagentaOnsetsFramesDrumBackend(
        command_template="/bin/echo --input {input} --output {output}",
        runner=runner,
    )
    result = backend.transcribe(drums, output, tempo_bpm=120.0)

    assert result["status"] == "completed"
    assert result["observed_drum_classes"] == ["kick", "snare"]
    assert "/tmp/" not in str(result)


def test_self_trained_backend_is_blocked_without_private_runtime_template(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GROOVESCRIBE_SELF_TRAINED_DRUM_COMMAND_TEMPLATE", raising=False)
    backend = SelfTrainedPrototypeDrumBackend()

    assert backend.availability() == BackendAvailability(
        "self_trained_prototype_drums",
        False,
        "self_trained_prototype_runtime_unavailable",
    )
    assert backend.transcribe(tmp_path / "drums.wav", tmp_path / "raw.mid", tempo_bpm=120.0)["status"] == "blocked"


def test_self_trained_multiclass_backend_is_blocked_without_private_runtime_template(monkeypatch) -> None:
    monkeypatch.delenv("GROOVESCRIBE_SELF_TRAINED_MULTICLASS_COMMAND_TEMPLATE", raising=False)

    assert SelfTrainedMulticlassDrumBackend().availability() == BackendAvailability(
        "self_trained_multiclass_drums",
        False,
        "self_trained_multiclass_runtime_unavailable",
    )


def test_self_trained_multilabel_backend_is_blocked_without_private_runtime_template(monkeypatch) -> None:
    monkeypatch.delenv("GROOVESCRIBE_SELF_TRAINED_MULTILABEL_COMMAND_TEMPLATE", raising=False)

    assert SelfTrainedMultilabelDrumBackend().availability() == BackendAvailability(
        "self_trained_multilabel_drums",
        False,
        "self_trained_multilabel_runtime_unavailable",
    )


def test_multilabel_training_rejects_augmentation_with_benchmark_source_drift() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("multilabel_train", root / "scripts" / "train_self_trained_multilabel_drum_model.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    source = {
        "training_source_ids": ["train"],
        "validation_source_ids": ["validation"],
        "benchmark_source_ids": ["benchmark"],
    }
    invalid = {
        "source_id_overlap_with_benchmark": False,
        "training_source_ids": ["train"],
        "validation_source_ids": ["validation"],
        "benchmark_source_ids": ["changed"],
        "items": [],
    }

    assert script._validate_augmentation(invalid, source) == "training_augmentation_source_id_isolation_invalid"


def test_self_trained_backend_requires_kick_snare_and_third_drum_class(tmp_path: Path) -> None:
    drums = tmp_path / "drums.wav"
    drums.write_bytes(b"audio")
    output = tmp_path / "raw.mid"

    def runner(command, **kwargs):
        output_path = Path(command[command.index("--output") + 1])
        write_drum_midi(
            output_path,
            (
                ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
                ProcessedDrumEvent(tick=240, note=38, drum="snare", velocity=100),
                ProcessedDrumEvent(tick=480, note=42, drum="closed_hat", velocity=100),
            ),
            ticks_per_beat=480,
        )
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    backend = SelfTrainedPrototypeDrumBackend(
        command_template="/bin/echo --input {input} --output {output} --tempo-bpm {tempo_bpm}",
        runner=runner,
    )
    result = backend.transcribe(drums, output, tempo_bpm=120.0)

    assert result["status"] == "completed"
    assert result["observed_drum_classes"] == ["closed_hat", "kick", "snare"]
    assert "/tmp/" not in str(result)


def test_self_trained_baseline_metadata_is_synthetic_and_source_isolated(monkeypatch, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("self_trained_baseline", root / "scripts" / "train_self_trained_drum_baseline.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    soundfont = tmp_path / "drums.sf2"
    soundfont.write_bytes(b"soundfont")

    def runner(command, **kwargs):
        Path(command[command.index("-F") + 1]).write_bytes(b"wav")
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(script, "_feature", lambda path, onset_seconds: np.ones(64, dtype=np.float32))
    config = type("Config", (), {"soundfont": soundfont, "output_dir": tmp_path / "runtime", "fluidsynth": Path("fluidsynth")})()

    result = script.train(config, runner=runner)
    metadata = (tmp_path / "runtime" / "training_metadata.json").read_text(encoding="utf-8")

    assert result["status"] == "completed"
    assert (tmp_path / "runtime" / "self_trained_drum_prototype_v1.npz").is_file()
    assert '"training_kind": "synthetic_isolated_drum_hits"' in metadata
    assert '"source_id_overlap_with_benchmark": false' in metadata
    assert "/tmp/" not in metadata


def test_gmd_training_manifest_excludes_all_benchmark_sources(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("gmd_manifest", root / "scripts" / "build_gmd_training_manifest.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    gmd = tmp_path / "gmd"
    gmd.mkdir()
    (gmd / "info.csv").write_text(
        "drummer,session,id,style,bpm,beat_type,time_signature,midi_filename,audio_filename,duration,split\n"
        "drummer1,s,one,rock,120,beat,4-4,drummer1/a.mid,drummer1/a.wav,1,train\n"
        "drummer2,s,two,rock,120,beat,4-4,drummer2/a.mid,drummer2/a.wav,1,train\n"
        "drummer3,s,three,rock,120,beat,4-4,drummer3/a.mid,drummer3/a.wav,1,validation\n"
        "drummer4,s,four,rock,120,beat,4-4,drummer4/a.mid,drummer4/a.wav,1,train\n",
        encoding="utf-8",
    )
    for drummer in ("drummer1", "drummer2", "drummer3", "drummer4"):
        (gmd / drummer).mkdir()
        (gmd / drummer / "a.mid").write_bytes(b"midi")
        (gmd / drummer / "a.wav").write_bytes(b"audio")
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(json.dumps({"items": [{"audio_path": str(gmd / "drummer1" / "a.wav")}] }), encoding="utf-8")
    output = tmp_path / "training.json"

    result = script.build_manifest(type("Config", (), {"gmd_root": gmd, "benchmark_manifest": benchmark, "output_manifest": output, "max_train_items": 10, "max_validation_items": 10})())

    assert result["status"] == "completed"
    assert result["benchmark_source_ids"] == ["drummer1"]
    assert set(result["training_source_ids"]).isdisjoint(result["benchmark_source_ids"])
    assert set(result["validation_source_ids"]).isdisjoint(result["benchmark_source_ids"])


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
    evaluation = script._integration_evaluation([{"status": "completed"}], comparison)
    assert evaluation == {
        "status": "rejected",
        "reason_codes": [
            "drum_only_core_false_positive_regression",
            "full_mix_core_false_positive_regression",
        ],
    }


def test_alternative_candidate_reports_missing_full_mix_metrics() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("alternative_evaluation", root / "scripts" / "run_alternative_drum_backend_spike.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    evaluation = script._integration_evaluation([{"status": "completed"}], {"drum_only": {"chart_f1_delta": 0.1, "per_drum": {}, "core_groove_f1": {}, "core_fp_total": {}, "gate_verdicts": {}}})

    assert evaluation["status"] == "rejected"
    assert "full_mix_metrics_missing" in evaluation["reason_codes"]


def test_alternative_gate_regression_is_scoped_to_its_input_type() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("alternative_gate_scope", root / "scripts" / "run_alternative_drum_backend_spike.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    passing = {
        "chart_f1_delta": 0.1,
        "per_drum": {drum: {"delta": 0.1} for drum in ("kick", "snare", "closed_hat")},
        "core_groove_f1": {"alternative": 0.8, "adtof": 0.7},
        "core_fp_total": {"alternative": 1, "adtof": 1},
        "gate_verdicts": {"alternative": {}, "adtof": {}},
    }
    runs = [
        {"status": "completed", "input_type": "drum_only", "performance_gate": {"verdict": "performance_ready"}, "adtof_performance_gate": {"verdict": "performance_ready"}},
        {"status": "completed", "input_type": "full_mix", "performance_gate": {"verdict": "not_ready"}, "adtof_performance_gate": {"verdict": "performance_ready"}},
    ]

    evaluation = script._integration_evaluation(runs, {"drum_only": passing, "full_mix": passing})

    assert evaluation["reason_codes"] == ["full_mix_performance_gate_regression"]


def test_alternative_spike_public_report_strips_unsafe_metrics_and_diagnostics() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("alternative_public_report", root / "scripts" / "run_alternative_drum_backend_spike.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    report = script._public_report({"status": "completed", "backend": "spectral_onset_spike", "runs": [{"id": "x", "status": "completed", "input_type": "drum_only", "raw_metrics": {"status": "measured", "f1": 0.5, "stdout": "/tmp/private"}, "performance_gate": {"verdict": "not_ready", "command": "secret"}}], "comparison_to_adtof": {}, "integration_evaluation": {"status": "rejected", "reason_codes": ["stdout_private"]}})

    serialized = json.dumps(report)
    assert "/tmp/" not in serialized
    assert "stdout" not in serialized
    assert "command" not in serialized


def test_comparison_exposes_raw_processed_and_chart_stage_metrics() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("alternative_comparison", root / "scripts" / "run_alternative_drum_backend_spike.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    metric = {"f1": 0.5, "mean_timing_error_ticks": 12.0, "per_drum": {drum: {"f1": 0.5, "fp": 0} for drum in ("kick", "snare", "closed_hat", "open_hat", "tom", "cymbal")}}
    comparison = script._comparison(
        [
            {
                "input_type": "drum_only",
                "raw_metrics": metric,
                "processed_metrics": metric,
                "chart_metrics": metric,
                "adtof_raw_metrics": metric,
                "adtof_processed_metrics": metric,
                "adtof_chart_metrics": metric,
                "performance_gate": {"verdict": "not_ready"},
                "adtof_performance_gate": {"verdict": "not_ready"},
            }
        ]
    )

    assert set(comparison["drum_only"]["stages"]) == {"raw", "processed", "chart"}
    assert comparison["drum_only"]["stages"]["processed"]["per_drum"]["snare"]["delta"] == 0.0


def test_alternative_backend_uses_canonical_candidate_artifacts(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("alternative_canonical", root / "scripts" / "run_alternative_drum_backend_spike.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    source, quality = script._canonical_adtof_source(
        tmp_path,
        {
            "quality": {"performance_gate": {"verdict": "not_ready"}},
            "candidate_analysis": {
                "canonical_candidate_id": "threshold_0_3",
                "candidates": [
                    {
                        "candidate_id": "threshold_0_3",
                        "status": "completed",
                        "quality": {"performance_gate": {"verdict": "playable_but_low_confidence"}},
                    }
                ],
            },
        },
    )

    assert source == tmp_path / "candidates" / "threshold_0_3"
    assert quality == {"performance_gate": {"verdict": "playable_but_low_confidence"}}


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


def test_error_breakdown_uses_canonical_candidate_artifacts(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("breakdown_canonical", root / "scripts" / "run_performance_error_breakdown.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    run = tmp_path / "run"
    pipeline = run / "logs" / "pipeline.json"
    pipeline.parent.mkdir(parents=True)
    pipeline.write_text(
        json.dumps(
            {
                "candidate_analysis": {
                    "canonical_candidate_id": "threshold_0_3",
                    "candidates": [{"candidate_id": "threshold_0_3", "status": "completed"}],
                }
            }
        ),
        encoding="utf-8",
    )

    assert script._canonical_candidate_root(run) == run / "candidates" / "threshold_0_3"


def test_raw_model_attribution_reports_safe_stage_metrics_and_holdout_contract(tmp_path: Path, monkeypatch) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("raw_model_attribution", root / "scripts" / "run_raw_model_attribution.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    truth = _midi(
        tmp_path / "truth.mid",
        (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),),
    )
    benchmark_dir = tmp_path / "benchmark"
    notation = benchmark_dir / "runs" / "safe-item" / "candidates" / "threshold_0_3" / "notation"
    midi = benchmark_dir / "runs" / "safe-item" / "candidates" / "threshold_0_3" / "midi"
    _midi(midi / "raw_drum.mid", (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),))
    _midi(midi / "processed_drum.mid", (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),))
    _midi(notation / "performance_score.mid", (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),))
    log = benchmark_dir / "runs" / "safe-item" / "logs" / "pipeline.json"
    log.parent.mkdir(parents=True)
    log.write_text(
        json.dumps(
            {
                "candidate_analysis": {
                    "candidates": [
                        {"candidate_id": "threshold_0_3", "status": "completed", "config": {"threshold": 0.3}},
                        {
                            "candidate_id": "threshold_0_6",
                            "status": "failed",
                            "failed_stage": "drum_transcription",
                            "failure_reason_code": "candidate_transcription_failed",
                            "config": {"threshold": 0.6},
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"items": [{"id": "safe-item", "audio_path": str(audio), "ground_truth_midi_path": str(truth), "input_type": "full_mix"}]}), encoding="utf-8")
    monkeypatch.setattr(script, "validate_item_provenance", lambda *_args, **_kwargs: None)

    report = script.run_attribution(type("Config", (), {"manifest": manifest, "benchmark_dir": benchmark_dir, "output_dir": tmp_path / "report"})())

    candidate = report["items"][0]["candidates"][0]
    assert candidate["stages"]["raw"]["per_drum"]["kick"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    failed = report["items"][0]["candidates"][1]
    assert failed["failure_category"] == "transcription"
    assert failed["failure_reason_code"] == "candidate_transcription_failed"
    assert report["data_split"]["status"] == "holdout_insufficient"
    assert report["separation_attribution"] == {
        "status": "unavailable",
        "reason": "reference_drums_audio_unavailable",
        "reference_drums_item_count": 0,
        "snr": {"status": "unavailable"},
    }
    assert "/tmp/" not in json.dumps(report)


def test_reference_drums_controlled_benchmark_compares_paired_inputs_without_diagnostics(tmp_path: Path, monkeypatch) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("reference_drums_controlled", root / "scripts" / "run_reference_drums_controlled_benchmark.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    class FakeTranscriber:
        def transcribe(self, _audio: Path, output_dir: Path) -> None:
            _midi(output_dir / "raw_drum.mid", (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),))

    class FakeFactory:
        @staticmethod
        def from_command_template_string(*_args, **_kwargs) -> FakeTranscriber:
            return FakeTranscriber()

    monkeypatch.setattr(script, "AdtofDrumTranscriber", FakeFactory)
    monkeypatch.setattr(script, "validate_item_provenance", lambda *_args, **_kwargs: None)
    items = []
    benchmark_dir = tmp_path / "benchmark"
    for item_id, split in (("development-item", "development"), ("holdout-item", "holdout")):
        audio = tmp_path / f"{item_id}-mix.wav"
        reference = tmp_path / f"{item_id}-drums.wav"
        audio.write_bytes(b"mix")
        reference.write_bytes(b"drums")
        truth = _midi(tmp_path / f"{item_id}-truth.mid", (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),))
        raw = benchmark_dir / "runs" / item_id / "candidates" / "threshold_0_3" / "midi" / "raw_drum.mid"
        _midi(raw, (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),))
        items.append({"id": item_id, "input_type": "full_mix", "audio_path": str(audio), "ground_truth_midi_path": str(truth), "reference_drums_audio_path": str(reference), "benchmark_split": split})
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"items": items}), encoding="utf-8")

    report = script.run_controlled_benchmark(
        type("Config", (), {"manifest": manifest, "benchmark_dir": benchmark_dir, "output_dir": tmp_path / "report", "threshold": 0.3, "adtof_command_template": "safe", "adtof_device": "cpu", "adtof_timeout_seconds": 1, "no_resume": False})()
    )

    assert report["status"] == "completed"
    assert report["summary"]["measured_item_count"] == 2
    assert report["items"][0]["reference_drums_adtof"]["f1"] == 1.0
    assert report["items"][0]["full_mix_demucs_adtof"]["f1"] == 1.0
    assert report["experiment_decision"] == {"status": "not_selected", "reason": "evidence_inconclusive"}
    assert "/tmp/" not in json.dumps(report)


def test_reference_drums_controlled_benchmark_pairs_separated_preset_artifacts(tmp_path: Path, monkeypatch) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("reference_drums_controlled_preset", root / "scripts" / "run_reference_drums_controlled_benchmark.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "validate_item_provenance", lambda *_args, **_kwargs: None)
    item_id = "preset-item"
    benchmark_dir = tmp_path / "benchmark"
    raw = benchmark_dir / "runs" / item_id / "candidates" / "preset_separated_v1" / "midi" / "raw_drum.mid"
    _midi(raw, (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),))
    truth = _midi(tmp_path / "truth.mid", (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),))
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"drums")

    assert script._candidate_id(0.3, "separated_v1") == "preset_separated_v1"
    assert script._candidate_raw_midi(benchmark_dir, item_id, script._candidate_id(0.3, "separated_v1")) == raw
    assert script._candidate_raw_midi(benchmark_dir, item_id, "threshold_0_3") is None


def test_reference_drums_controlled_benchmark_separates_reference_artifacts_by_strategy(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("reference_drums_controlled_strategy_paths", root / "scripts" / "run_reference_drums_controlled_benchmark.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    output = tmp_path / "report"
    scalar = output / "items" / "item" / "reference_drums_adtof" / script._candidate_id(0.3, None) / "raw_drum.mid"
    preset = output / "items" / "item" / "reference_drums_adtof" / script._candidate_id(0.3, "separated_v1") / "raw_drum.mid"

    assert scalar != preset
    assert scalar.parent.name == "threshold_0_3"
    assert preset.parent.name == "preset_separated_v1"


def test_raw_model_attribution_whitelists_preset_candidate_strategy() -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("raw_model_attribution_preset", root / "scripts" / "run_raw_model_attribution.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    public = script._public_candidate({"candidate_id": "preset_separated_v1", "threshold": None, "strategy": "adtof_preset_v1", "adtof_threshold_preset": "separated_v1", "status": "completed", "stages": {}})

    assert public["strategy"] == "adtof_preset_v1"
    assert public["adtof_threshold_preset"] == "separated_v1"

    inconsistent = script._public_candidate({"candidate_id": "invalid", "strategy": "scalar_threshold_v1", "adtof_threshold_preset": "separated_v1", "status": "completed", "stages": {}})
    assert inconsistent["strategy"] == "scalar_threshold_v1"
    assert inconsistent["adtof_threshold_preset"] is None
