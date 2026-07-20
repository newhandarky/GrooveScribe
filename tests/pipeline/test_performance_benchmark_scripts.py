from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent
from ai_pipeline.benchmark.provenance import sha256

def _load_script(name: str):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(name, root / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_is_skipped_without_external_manifest(tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    config = type("Config", (), {"manifest": None, "output_dir": tmp_path, "python": Path("python"), "adtof_command_template": None, "adtof_device": "cpu", "demucs_device": "cpu", "mock_ai": False})()

    report = script.run_benchmark(config)

    assert report["status"] == "skipped"
    assert report["summary"]["reason"] == "benchmark_manifest_not_provided"
    assert (tmp_path / "performance_benchmark_report.json").exists()
    assert not any(token in (tmp_path / "performance_benchmark_report.json").read_text(encoding="utf-8") for token in ("/tmp/", "/Users/", "command_template"))


def test_external_bootstrap_blocks_cleanly_when_roots_are_missing(tmp_path: Path) -> None:
    script = _load_script("bootstrap_external_performance_benchmarks")
    config = type(
        "Config",
        (),
        {
            "gmd_root": tmp_path / "missing-gmd",
            "slakh_root": tmp_path / "missing-slakh",
            "output_manifest": tmp_path / "private_manifest.json",
            "gmd_limit": 1,
            "slakh_limit": 1,
        },
    )()

    report = script.bootstrap(config)

    assert report["status"] == "blocked"
    assert report["gmd_reason"] == "gmd_info_csv_missing"
    assert report["slakh_reason"] in {"slakh_insufficient_valid_pairs", "slakh_yaml_parser_unavailable"}
    assert "/tmp/" not in json.dumps(report)
    assert not config.output_manifest.exists()


def test_external_bootstrap_writes_private_licensed_manifest_with_checksum_metadata(tmp_path: Path) -> None:
    script = _load_script("bootstrap_external_performance_benchmarks")
    gmd_root = tmp_path / "gmd"
    slakh_track = tmp_path / "slakh" / "Track00001"
    gmd_root.mkdir(parents=True)
    (gmd_root / "audio.wav").write_bytes(b"gmd-audio")
    write_drum_midi(
        gmd_root / "drums.mid",
        (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),),
        ticks_per_beat=480,
    )
    (gmd_root / "info.csv").write_text(
        "id,audio_filename,midi_filename,bpm,time_signature,style,drummer,session\n"
        "gmd-one,audio.wav,drums.mid,120,4/4,funk,drummer1,session1\n",
        encoding="utf-8",
    )
    (slakh_track / "MIDI").mkdir(parents=True)
    (slakh_track / "mix.wav").write_bytes(b"slakh-mix")
    write_drum_midi(
        slakh_track / "MIDI" / "S00.mid",
        (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),),
        ticks_per_beat=480,
    )
    (slakh_track / "metadata.yaml").write_text(
        "stems:\n  S00:\n    is_drum: true\n    midi_saved: false\n",
        encoding="utf-8",
    )
    config = type(
        "Config",
        (),
        {
            "gmd_root": gmd_root,
            "slakh_root": tmp_path / "slakh",
            "output_manifest": tmp_path / "private_manifest.json",
            "gmd_limit": 1,
            "slakh_limit": 1,
        },
    )()

    report = script.bootstrap(config)
    manifest = json.loads(config.output_manifest.read_text(encoding="utf-8"))

    assert report["status"] == "completed"
    assert "/tmp/" not in json.dumps(report)
    assert {item["input_type"] for item in manifest["items"]} == {"drum_only", "full_mix"}
    for item in manifest["items"]:
        assert item["license"] == "CC BY 4.0"
        assert item["license_url"].startswith("https://")
        assert item["source_release"]
        assert set(item["sha256"]) == {"audio", "ground_truth_midi"}
        assert len(item["sha256"]["audio"]) == 64
        assert item["usage_scope"]
        assert item["ground_truth_verified"] is True
    slakh = next(item for item in manifest["items"] if item["input_type"] == "full_mix")
    assert slakh["synthetic_full_mix"] is True
    assert slakh["real_audio_verified"] is False
    gmd = next(item for item in manifest["items"] if item["input_type"] == "drum_only")
    assert gmd["time_signature"] == "4/4"


def test_public_benchmark_item_marks_synthetic_full_mix_as_not_real_audio_verified() -> None:
    script = _load_script("run_performance_benchmark")

    public = script._public_item("slakh-track", {"input_type": "full_mix", "synthetic_full_mix": True})

    assert public["synthetic_full_mix"] is True
    assert public["real_audio_verified"] is False


def test_benchmark_parser_uses_configured_adtof_template(monkeypatch, tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    monkeypatch.setenv("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE", "adtof --audio {input} --out {output}")
    monkeypatch.setattr(sys, "argv", ["benchmark", "--output-dir", str(tmp_path)])

    args = script.parse_args()

    assert args.adtof_command_template == "adtof --audio {input} --out {output}"


def test_benchmark_provenance_requires_license_ground_truth_and_matching_checksums(tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    midi = tmp_path / "truth.mid"
    write_drum_midi(midi, (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),), ticks_per_beat=480)
    item = {
        "id": "licensed-item",
        "audio_path": str(audio),
        "ground_truth_midi_path": str(midi),
        "tempo_bpm": 120.0,
        "time_signature": "4/4",
        "input_type": "drum_only",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source": "official",
        "source_release": "v1",
        "renderer": "dataset_recording",
        "usage_scope": "licensed_ground_truth_drum_only",
        "calibration_eligible": True,
        "ground_truth_verified": True,
        "synthetic_full_mix": False,
        "real_audio_verified": True,
        "sha256": {"audio": sha256(audio), "ground_truth_midi": sha256(midi)},
        "acceptance": {
            "minimum_f1": 0.75,
            "minimum_per_drum_f1": {"kick": 0.7},
            "minimum_core_groove_accuracy": 0.7,
            "maximum_mean_timing_error_ticks": 72,
        },
    }

    assert script.validate_item_provenance(item, audio, midi) is None
    item["sha256"]["audio"] = "0" * 64
    assert script.validate_item_provenance(item, audio, midi) == "benchmark_checksum_mismatch"
    item["sha256"]["audio"] = sha256(audio)
    item["source"] = "stdout /tmp/private-recording"
    assert script.validate_item_provenance(item, audio, midi) == "benchmark_provenance_invalid"
    public = script._public_item("licensed-item", item)
    assert set(public) == {
        "id",
        "input_type",
        "tempo_bpm",
        "time_signature",
        "license",
        "renderer",
        "calibration_eligible",
        "synthetic_full_mix",
        "real_audio_verified",
    }
    assert "/tmp/" not in json.dumps(public)
    item["source"] = "official"
    item["acceptance"]["minimum_f1"] = float("nan")
    assert script.validate_item_provenance(item, audio, midi) == "benchmark_provenance_invalid"


def test_benchmark_provenance_rejects_audio_or_ground_truth_inside_repository_root(tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    midi = tmp_path / "truth.mid"
    write_drum_midi(midi, (ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),), ticks_per_beat=480)
    item = {
        "id": "repo-local-item",
        "audio_path": str(audio),
        "ground_truth_midi_path": str(midi),
        "tempo_bpm": 120.0,
        "time_signature": "4/4",
        "input_type": "drum_only",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source": "official",
        "source_release": "v1",
        "renderer": "dataset_recording",
        "usage_scope": "licensed_ground_truth_drum_only",
        "calibration_eligible": True,
        "ground_truth_verified": True,
        "synthetic_full_mix": False,
        "real_audio_verified": True,
        "sha256": {"audio": sha256(audio), "ground_truth_midi": sha256(midi)},
        "acceptance": {
            "minimum_f1": 0.75,
            "minimum_per_drum_f1": {"kick": 0.7},
            "minimum_core_groove_accuracy": 0.7,
            "maximum_mean_timing_error_ticks": 72,
        },
    }

    assert script.validate_item_provenance(item, audio, midi, repository_root=tmp_path) == "benchmark_artifact_must_be_outside_repo"


def test_benchmark_rejects_repo_local_manifest_and_output_directory(tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    repo_root = Path(__file__).resolve().parents[2]
    local_manifest = repo_root / "benchmarks" / "performance" / "manifest.schema.json"
    config = type(
        "Config",
        (),
        {
            "manifest": local_manifest,
            "output_dir": tmp_path,
            "python": Path("python"),
            "adtof_command_template": None,
            "adtof_device": "cpu",
            "demucs_device": "cpu",
            "mock_ai": False,
        },
    )()

    assert script.run_benchmark(config)["summary"]["reason"] == "benchmark_manifest_must_be_outside_repo"
    config.manifest = None
    config.output_dir = repo_root / "benchmarks" / "performance" / "blocked-output"
    assert script.run_benchmark(config)["summary"]["reason"] == "benchmark_output_dir_must_be_outside_repo"


def test_benchmark_cli_manifest_overrides_environment_manifest(monkeypatch, tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    environment_manifest = tmp_path / "environment.json"
    explicit_manifest = tmp_path / "explicit.json"
    monkeypatch.setenv("GROOVESCRIBE_PERFORMANCE_BENCHMARK_MANIFEST", str(environment_manifest))
    monkeypatch.setattr(
        sys,
        "argv",
        ["benchmark", "--output-dir", str(tmp_path), "--manifest", str(explicit_manifest)],
    )

    args = script.parse_args()

    assert args.manifest == explicit_manifest


def test_benchmark_parser_accepts_product_preset_and_filter(monkeypatch, tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark",
            "--output-dir",
            str(tmp_path),
            "--adtof-threshold-preset",
            "separated_v1",
            "--tom-filter-preset",
            "tom_guard_v1",
        ],
    )

    args = script.parse_args()

    assert args.adtof_threshold_preset == "separated_v1"
    assert args.tom_filter_preset == "tom_guard_v1"


def test_benchmark_requires_the_versioned_candidate_threshold_profile(tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    config = type(
        "Config",
        (),
        {
            "manifest": None,
            "output_dir": tmp_path,
            "python": Path("python"),
            "adtof_command_template": None,
            "adtof_device": "cpu",
            "demucs_device": "cpu",
            "candidate_thresholds": "0.3,0.5",
            "mock_ai": False,
        },
    )()

    report = script.run_benchmark(config)

    assert report["status"] == "blocked"
    assert report["summary"]["reason"] == "candidate_thresholds_must_match_quality_profile"
    assert script._candidate_thresholds("0.30,0.40,0.50,0.60") == ("0.3", "0.4", "0.5", "0.6")
    assert script._QUALITY_PROFILE["selection_order"] == [
        "ground_truth_acceptance",
        "chart_midi_f1",
        "core_groove_accuracy",
        "mean_timing_error_ticks",
    ]


def test_benchmark_report_strips_raw_performance_gate_after_calibration(monkeypatch, tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    manifest = tmp_path / "private_manifest.json"
    manifest.write_text(json.dumps({"items": [{"id": "fixture"}]}), encoding="utf-8")
    raw_gate = {
        "verdict": "performance_ready",
        "uncalibrated_verdict": "performance_ready",
        "delivery_allowed": True,
        "blocking_issues": ["/tmp/private-issue"],
        "audio_alignment": {"onset_alignment_rate": 0.9, "stdout": "/Users/private"},
        "midi": {"debug_path": "/private/var/folders/secret"},
    }
    monkeypatch.setattr(
        script,
        "_run_item",
        lambda *_args: {
            "id": "fixture",
            "status": "completed",
            "ground_truth_verified": True,
            "real_audio_verified": False,
            "synthetic_full_mix": True,
            "input_type": "drum_only",
            "ground_truth_eval": {"status": "measured", "f1": 1.0},
            "ground_truth_passed": True,
            "calibration_eligible": False,
            "performance_gate": raw_gate,
            "candidate_recommendation_validation": {"status": "passed"},
        },
    )
    config = type(
        "Config",
        (),
        {
            "manifest": manifest,
            "output_dir": tmp_path / "report",
            "python": Path("python"),
            "adtof_command_template": None,
            "adtof_device": "cpu",
            "demucs_device": "cpu",
            "candidate_thresholds": None,
            "mock_ai": False,
        },
    )()

    report = script.run_benchmark(config)

    run = report["runs"][0]
    assert run["performance_gate"] == {"verdict": "performance_ready", "onset_alignment_rate": 0.9}
    assert run["calibrated_gate"] == {
        "verdict": "playable_but_low_confidence",
        "onset_alignment_rate": 0.9,
        "ground_truth_verified": True,
        "calibration_status": "not_applied",
    }
    assert not any(token in json.dumps(report) for token in ("/tmp/", "/Users/", "stdout", "debug_path"))


def test_generated_fixture_contract_measures_all_profile_candidates_with_one_pipeline_run(tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    audio = tmp_path / "synthetic.wav"
    audio.write_bytes(b"synthetic-audio")
    ground_truth = tmp_path / "ground_truth.mid"
    events = (
        ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=240, note=42, drum="closed_hat", velocity=80),
        ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=100),
    )
    write_drum_midi(ground_truth, events, ticks_per_beat=480)
    manifest = tmp_path / "generated_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "generated-fixture",
                        "audio_path": str(audio),
                        "ground_truth_midi_path": str(ground_truth),
                        "tempo_bpm": 120,
                        "time_signature": "4/4",
                        "input_type": "drum_only",
                        "license": "generated_synthetic",
                        "license_url": "https://example.invalid/generated",
                        "source": "generated_fixture",
                        "source_release": "v1",
                        "renderer": "synthetic_signal",
                        "usage_scope": "generated_regression",
                        "calibration_eligible": False,
                        "ground_truth_verified": True,
                        "synthetic_full_mix": False,
                        "real_audio_verified": False,
                        "sha256": {"audio": sha256(audio), "ground_truth_midi": sha256(ground_truth)},
                        "acceptance": {**_candidate_acceptance(), "minimum_per_drum_f1": {"kick": 0.0}},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        output_dir = Path(command[command.index("--output-dir") + 1])
        candidates = []
        for threshold in ("0_3", "0_4", "0_5", "0_6"):
            candidate_id = f"threshold_{threshold}"
            _write_score(output_dir / "candidates" / candidate_id / "notation", events)
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "status": "completed",
                    "selected": candidate_id == "threshold_0_4",
                    "config": {"threshold": float(threshold.replace("_", "."))},
                    "quality": {
                        "processed_drum_counts": {"kick": 1, "snare": 1, "closed_hat": 1},
                        "quality_flags": [],
                        "notation_readability": {"measure_count": 1, "raw_pipeline_value": "/tmp/private"},
                        "performance_gate": {
                            "verdict": "playable_but_low_confidence",
                            "audio_alignment": {"onset_alignment_rate": 0.8, "stderr": "private"},
                        },
                    },
                    "recommendation": {
                        "score": 90,
                        "recommendation": "recommended_for_practice",
                        "rejected": False,
                    },
                }
            )
        pipeline = {
            "quality": {
                "performance_gate": {
                    "verdict": "playable_but_low_confidence",
                    "uncalibrated_verdict": "playable_but_low_confidence",
                    "audio_alignment": {"onset_alignment_rate": 0.8, "stdout": "/tmp/private"},
                }
            },
            "candidate_analysis": {
                "recommended_candidate_id": "threshold_0_4",
                "canonical_candidate_id": "threshold_0_4",
                "candidates": candidates,
            },
        }
        logs = output_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        return type("Result", (), {"returncode": 0})()

    config = type(
        "Config",
        (),
        {
            "manifest": manifest,
            "output_dir": tmp_path / "report",
            "python": Path("python"),
            "adtof_command_template": None,
            "adtof_device": "cpu",
            "demucs_device": "cpu",
            "candidate_thresholds": None,
            "mock_ai": False,
        },
    )()

    report = script.run_benchmark(config, process_runner=runner)

    assert report["status"] == "completed"
    assert len(calls) == 1
    assert calls[0][calls[0].index("--candidate-thresholds") + 1] == "0.3,0.4,0.5,0.6"
    assert calls[0][calls[0].index("--demucs-model-name") + 1] == "htdemucs"
    run = report["runs"][0]
    assert len(run["candidate_evaluation"]) == 4
    assert run["ground_truth_eval"]["f1"] == 1.0
    assert run["candidate_recommendation_validation"]["status"] == "passed"
    assert run["performance_gate"] == {"verdict": "playable_but_low_confidence", "onset_alignment_rate": 0.8}
    assert not any(token in json.dumps(report) for token in ("/tmp/", "stdout", "stderr", "raw_pipeline_value"))


def test_synthetic_generator_writes_external_manifest(monkeypatch, tmp_path: Path) -> None:
    script = _load_script("generate_performance_benchmark_fixtures")
    monkeypatch.setattr("sys.argv", ["generate", "--output-dir", str(tmp_path)])

    assert script.main() == 0
    manifest = json.loads((tmp_path / "performance_benchmark_manifest.json").read_text(encoding="utf-8"))
    assert {item["input_type"] for item in manifest["items"]} == {"drum_only", "full_mix"}
    assert all(Path(item["audio_path"]).exists() and Path(item["ground_truth_midi_path"]).exists() for item in manifest["items"])
    assert all(item["calibration_eligible"] is False for item in manifest["items"])


def test_realistic_generator_reports_soundfont_blocker_without_paths(tmp_path: Path) -> None:
    script = _load_script("generate_realistic_performance_benchmark")
    config = type("Config", (), {"output_dir": tmp_path, "soundfont": None, "fluidsynth": "fluidsynth", "ffmpeg": "ffmpeg"})()

    report = script.generate(config, which=lambda _binary: None)

    assert report == {"schema_version": "1.0", "status": "blocked", "reason": "soundfont_not_configured", "manifest_name": None}
    assert "/tmp/" not in (tmp_path / "realistic_benchmark_status.json").read_text(encoding="utf-8")


def test_realistic_generator_manifest_declares_core_groove_acceptance(tmp_path: Path) -> None:
    script = _load_script("generate_realistic_performance_benchmark")
    config = type("Config", (), {"output_dir": tmp_path, "soundfont": tmp_path / "kit.sf2", "fluidsynth": "fluidsynth", "ffmpeg": "ffmpeg"})()
    config.soundfont.write_bytes(b"placeholder")

    commands = []

    def runner(command, **_kwargs):
        commands.append(command)
        output = Path(command[command.index("-F") + 1]) if "-F" in command else Path(command[-1])
        output.write_bytes(b"audio")
        return type("Result", (), {"returncode": 0})()

    report = script.generate(config, run=runner, which=lambda _binary: "/usr/bin/tool")

    assert report["status"] == "completed"
    manifest = json.loads((tmp_path / "realistic_performance_benchmark_manifest.json").read_text(encoding="utf-8"))
    assert all(item["acceptance"]["minimum_core_groove_accuracy"] == 0.75 for item in manifest["items"])
    assert (tmp_path / "full_mix_backbeat.backing.mid").exists()
    render_commands = [command for command in commands if command[0] == "fluidsynth"]
    assert render_commands
    for command in render_commands:
        output = command[3]
        assert command == [
            "fluidsynth",
            "-ni",
            "-F",
            output,
            "-r",
            "44100",
            str(config.soundfont),
            command[-1],
        ]
        assert command[-1].endswith(".mid")


def test_reference_acceptance_requires_core_groove_accuracy() -> None:
    script = _load_script("run_performance_benchmark")
    comparison = {
        "status": "measured",
        "f1": 0.95,
        "mean_timing_error_ticks": 2,
        "per_drum": {"kick": {"f1": 0.95}, "snare": {"f1": 0.95}},
    }
    acceptance = {
        "minimum_f1": 0.9,
        "minimum_per_drum_f1": {"kick": 0.9, "snare": 0.9},
        "minimum_core_groove_accuracy": 0.8,
        "maximum_mean_timing_error_ticks": 8,
    }

    assert script._reference_passed(comparison, {"status": "measured", "accuracy": 0.5}, acceptance) is False
    assert script._reference_passed(comparison, {"status": "unavailable", "accuracy": None}, acceptance) is False
    assert script._reference_passed(comparison, {"status": "measured", "accuracy": 0.9}, acceptance) is True


def test_core_groove_accuracy_checks_onset_slots_not_only_drum_presence(tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    ground_truth = tmp_path / "ground_truth.mid"
    write_drum_midi(
        ground_truth,
        (
            ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
            ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=100),
            ProcessedDrumEvent(tick=0, note=42, drum="closed_hat", velocity=80),
            ProcessedDrumEvent(tick=480, note=42, drum="closed_hat", velocity=80),
        ),
        ticks_per_beat=480,
    )
    chart = {
        "ticks_per_beat": 480,
        "time_signature": "4/4",
        "events": [
            {"tick": 0, "drum": "kick"},
            {"tick": 720, "drum": "snare"},
            {"tick": 0, "drum": "closed_hat"},
            {"tick": 480, "drum": "closed_hat"},
        ],
    }
    chart_path = tmp_path / "chart_events.json"
    chart_path.write_text(json.dumps(chart), encoding="utf-8")

    score = script._core_groove_accuracy(chart_path, ground_truth)

    assert score["metric"] == "macro_measure_core_onset_f1_eighth_grid"
    assert score["accuracy"] < 1.0


def test_core_groove_accuracy_respects_non_four_four_measure_length(tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    ground_truth = tmp_path / "ground_truth.mid"
    write_drum_midi(
        ground_truth,
        (
            ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
            ProcessedDrumEvent(tick=960, note=38, drum="snare", velocity=100),
        ),
        ticks_per_beat=480,
        time_signature="6/8",
    )
    chart_path = tmp_path / "chart_events.json"
    chart_path.write_text(
        json.dumps({"ticks_per_beat": 480, "time_signature": "6/8", "events": [{"tick": 0, "drum": "kick"}, {"tick": 960, "drum": "snare"}]}),
        encoding="utf-8",
    )

    score = script._core_groove_accuracy(chart_path, ground_truth)

    assert score["accuracy"] == 1.0


def test_candidate_benchmark_rejects_recommendation_that_regresses_from_ground_truth_best(tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    ground_truth = tmp_path / "ground_truth.mid"
    events = (
        ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=240, note=42, drum="closed_hat", velocity=80),
        ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=100),
    )
    write_drum_midi(ground_truth, events, ticks_per_beat=480)
    _write_candidate_score(tmp_path, "threshold_0_3", (events[0],))
    _write_candidate_score(tmp_path, "threshold_0_4", events)
    analysis = {
        "recommended_candidate_id": "threshold_0_3",
        "candidates": [
            _candidate("threshold_0_3", 0.3),
            _candidate("threshold_0_4", 0.4),
        ],
    }

    result = script._evaluate_candidates(
        analysis,
        output_dir=tmp_path,
        ground_truth=ground_truth,
        acceptance=_candidate_acceptance(),
    )

    assert result["validation"] == {
        "status": "failed",
        "recommended_candidate_id": "threshold_0_3",
        "best_candidate_id": "threshold_0_4",
        "profile": "ground_truth_candidate_v1",
    }
    assert result["candidates"][0]["quality_flags"] == ["sparse_transcription"]
    assert "stdout" not in json.dumps(result)
    assert "/tmp/" not in json.dumps(result)


def test_candidate_benchmark_accepts_recommended_ground_truth_best_and_uses_fixed_whitelist(tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    ground_truth = tmp_path / "ground_truth.mid"
    events = (
        ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=240, note=42, drum="closed_hat", velocity=80),
        ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=100),
    )
    write_drum_midi(ground_truth, events, ticks_per_beat=480)
    _write_candidate_score(tmp_path, "threshold_0_4", events)
    candidate = _candidate("threshold_0_4", 0.4)
    candidate["quality"]["processed_drum_counts"]["untrusted"] = 999
    candidate["quality"]["quality_flags"] = ["sparse_transcription", "stdout /tmp/unsafe"]
    result = script._evaluate_candidates(
        {"recommended_candidate_id": "threshold_0_4", "candidates": [candidate]},
        output_dir=tmp_path,
        ground_truth=ground_truth,
        acceptance=_candidate_acceptance(),
    )

    assert result["validation"]["status"] == "passed"
    assert result["candidates"][0]["processed_drum_counts"] == {"closed_hat": 1, "kick": 1, "snare": 1}
    assert result["candidates"][0]["quality_flags"] == ["sparse_transcription"]
    assert set(result["candidates"][0]["ground_truth_eval"]) == {
        "status",
        "f1",
        "mean_timing_error_ticks",
        "per_drum",
    }
    assert all(set(metrics) == {"f1"} for metrics in result["candidates"][0]["ground_truth_eval"]["per_drum"].values())
    assert set(result["candidates"][0]["core_groove_accuracy"]) == {"status", "accuracy"}


def test_candidate_quality_comparison_uses_raw_precision_but_never_reports_it() -> None:
    script = _load_script("run_performance_benchmark")
    accepted = {"ground_truth_passed": True, "ground_truth_eval": {"f1": 0.5, "mean_timing_error_ticks": 12.0}, "core_groove_accuracy": {"accuracy": 0.5}}
    slightly_better = {
        **accepted,
        "candidate_id": "threshold_0_4",
        "_raw_ground_truth_eval": {"f1": 0.500049, "mean_timing_error_ticks": 12.00001},
        "_raw_core_groove_accuracy": {"accuracy": 0.500049},
    }
    slightly_worse = {
        **accepted,
        "candidate_id": "threshold_0_3",
        "_raw_ground_truth_eval": {"f1": 0.500041, "mean_timing_error_ticks": 12.00002},
        "_raw_core_groove_accuracy": {"accuracy": 0.500041},
    }

    assert max([slightly_worse, slightly_better], key=script._candidate_quality_key)["candidate_id"] == "threshold_0_4"
    public = script._public_candidate_evaluation(slightly_better)
    assert "_raw_ground_truth_eval" not in public
    assert "_raw_core_groove_accuracy" not in public


def test_configured_benchmark_blocks_missing_measurements_and_fails_quality_regressions() -> None:
    script = _load_script("run_performance_benchmark")

    assert script._benchmark_status([], measured_count=0, reference_failures=0, recommendation_failures=0) == "blocked"
    assert script._benchmark_status(
        [{"status": "completed"}], measured_count=1, reference_failures=0, recommendation_failures=1
    ) == "failed"


def _candidate(candidate_id: str, threshold: float) -> dict:
    return {
        "candidate_id": candidate_id,
        "status": "completed",
        "selected": candidate_id == "threshold_0_4",
        "config": {"threshold": threshold},
        "quality": {
            "processed_drum_counts": {"kick": 1, "snare": 1, "closed_hat": 1},
            "quality_flags": ["sparse_transcription"],
            "performance_gate": {"verdict": "playable_but_low_confidence", "audio_alignment": {"onset_alignment_rate": 0.8}},
        },
        "recommendation": {"score": 80, "recommendation": "recommended_for_practice", "rejected": False},
    }


def _write_candidate_score(output_dir: Path, candidate_id: str, events: tuple[ProcessedDrumEvent, ...]) -> None:
    notation = output_dir / "candidates" / candidate_id / "notation"
    _write_score(notation, events)


def _write_score(notation: Path, events: tuple[ProcessedDrumEvent, ...]) -> None:
    notation.mkdir(parents=True)
    write_drum_midi(notation / "performance_score.mid", events, ticks_per_beat=480)
    notation.joinpath("chart_events.json").write_text(
        json.dumps(
            {
                "ticks_per_beat": 480,
                "time_signature": "4/4",
                "events": [{"tick": event.tick, "drum": event.drum} for event in events],
            }
        ),
        encoding="utf-8",
    )


def _candidate_acceptance() -> dict:
    return {
        "minimum_f1": 0.0,
        "minimum_per_drum_f1": {},
        "minimum_core_groove_accuracy": 0.0,
        "maximum_mean_timing_error_ticks": 120,
    }
