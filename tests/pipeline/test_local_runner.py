import json
import math
import struct
import wave
from pathlib import Path

from ai_pipeline.local_runner import LocalPipelineConfig, LocalPipelineRunner, _candidate_failure_reason_code


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 22_050
    frames = int(sample_rate * 0.25)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for index in range(frames):
            value = int(0.2 * 32767 * math.sin(2 * math.pi * 440 * index / sample_rate))
            wav_file.writeframes(struct.pack("<h", value))


def test_local_runner_completes_with_mock_ai(tmp_path) -> None:
    input_path = tmp_path / "input.wav"
    _write_wav(input_path)

    result = LocalPipelineRunner(LocalPipelineConfig(mock_ai=True)).run(input_path, tmp_path / "job")

    assert result.status == "completed"
    assert (tmp_path / "job" / "audio" / "normalized.wav").exists()
    assert (tmp_path / "job" / "stems" / "drums.wav").exists()
    assert not (tmp_path / "job" / "stems" / "no_drums.wav").exists()
    assert (tmp_path / "job" / "midi" / "raw_drum.mid").exists()
    assert (tmp_path / "job" / "midi" / "processed_drum.mid").exists()
    assert (tmp_path / "job" / "midi" / "drum_events.json").exists()
    assert result.artifacts["musicxml"].exists()
    assert result.artifacts["musicxml"].parent == tmp_path / "job" / "notation"
    assert (tmp_path / "job" / "notation" / "performance_score.musicxml").exists()
    assert (tmp_path / "job" / "notation" / "performance_score.mid").exists()
    payload = json.loads((tmp_path / "job" / "logs" / "pipeline.json").read_text(encoding="utf-8"))
    assert payload["quality"]["performance_gate"]["verdict"] in {"playable_but_low_confidence", "needs_better_source", "not_ready"}

    log_payload = json.loads(result.log_path.read_text(encoding="utf-8"))
    assert log_payload["status"] == "completed"
    assert [stage["name"] for stage in log_payload["stages"]] == [
        "audio_preprocessing",
        "source_separation",
        "drum_transcription",
        "midi_post_processing",
        "notation_generation",
    ]
    assert log_payload["quality"]["raw_event_count"] == 5
    assert log_payload["quality"]["processed_event_count"] == 5
    assert log_payload["quality"]["processed_drum_counts"] == {"closed_hat": 2, "kick": 2, "snare": 1}
    assert "sparse_transcription" in log_payload["quality"]["quality_flags"]


def test_local_runner_records_failed_stage(tmp_path) -> None:
    input_path = tmp_path / "missing.wav"

    try:
        LocalPipelineRunner().run(input_path, tmp_path / "job")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")


def test_candidate_failure_reason_codes_are_fixed_and_do_not_forward_runtime_messages() -> None:
    assert _candidate_failure_reason_code("drum_transcription") == "candidate_transcription_failed"
    assert _candidate_failure_reason_code("midi_post_processing") == "candidate_postprocess_failed"
    assert _candidate_failure_reason_code("notation_generation") == "candidate_notation_failed"
    assert _candidate_failure_reason_code("stdout /tmp/private") is None


def test_true_ai_candidate_analysis_reuses_preprocessing_and_separation_once(tmp_path, monkeypatch) -> None:
    input_path = tmp_path / "input.wav"
    _write_wav(input_path)
    calls: list[tuple[str, float]] = []
    transcription_configs: list[tuple[float, dict[str, float] | None, str | None]] = []

    def write(path, content=b"artifact"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def preprocess(self, _artifacts, output_dir):
        calls.append(("preprocess", self.config.adtof_threshold))
        return {"normalized_audio": write(output_dir / "audio" / "normalized.wav")}, {"duration_seconds": 8.0}

    def separate(self, _artifacts, output_dir):
        calls.append(("separate", self.config.adtof_threshold))
        return {
            "drums_stem": write(output_dir / "stems" / "drums.wav"),
            "accompaniment_stem": write(output_dir / "stems" / "no_drums.wav"),
        }, {"accompaniment_available": True}

    def transcribe(self, _artifacts, output_dir):
        calls.append(("transcribe", self.config.adtof_threshold))
        transcription_configs.append(
            (self.config.adtof_threshold, self.config.adtof_class_thresholds, self.config.adtof_threshold_preset)
        )
        return {"raw_midi": write(output_dir / "midi" / "raw_drum.mid")}, {"event_count": 12}

    def postprocess(self, _artifacts, output_dir):
        calls.append(("postprocess", self.config.adtof_threshold))
        return {
            "processed_midi": write(output_dir / "midi" / "processed_drum.mid"),
            "drum_events": write(output_dir / "midi" / "drum_events.json", b"{}"),
        }, {
            "input_event_count": 12,
            "output_event_count": 12,
            "processed_drum_counts": {"kick": 3, "snare": 3, "closed_hat": 6},
            "quality_flags": [],
            "warnings": [],
        }

    def notation(self, _artifacts, output_dir):
        calls.append(("notation", self.config.adtof_threshold))
        return {
            "musicxml": write(output_dir / "notation" / "score.musicxml"),
            "performance_midi": write(output_dir / "notation" / "performance_score.mid"),
            "chart_events": write(output_dir / "notation" / "chart_events.json", b"{}"),
        }, {
            "validation": {
                "musicxml": {"available": True, "parseable": True, "warnings": []},
                "pdf": {"available": False, "optional": True, "openable": None, "warnings": []},
            },
            "readability": {"dense_measure_count": 0},
            "performance_gate": {"verdict": "playable_but_low_confidence"},
        }

    monkeypatch.setattr(LocalPipelineRunner, "_run_audio_preprocessing", preprocess)
    monkeypatch.setattr(LocalPipelineRunner, "_run_source_separation", separate)
    monkeypatch.setattr(LocalPipelineRunner, "_run_drum_transcription", transcribe)
    monkeypatch.setattr(LocalPipelineRunner, "_run_midi_post_processing", postprocess)
    monkeypatch.setattr(LocalPipelineRunner, "_run_notation_generation", notation)

    result = LocalPipelineRunner(
        LocalPipelineConfig(candidate_thresholds=(0.3, 0.4), adtof_threshold_preset="separated_v1", tom_filter_preset="tom_guard_v1")
    ).run(input_path, tmp_path / "job")

    assert result.status == "completed"
    assert [name for name, _threshold in calls].count("preprocess") == 1
    assert [name for name, _threshold in calls].count("separate") == 1
    assert [threshold for name, threshold in calls if name == "transcribe"] == [0.3, 0.4]
    assert transcription_configs == [(0.3, None, None), (0.4, None, None)]
    payload = json.loads(result.log_path.read_text(encoding="utf-8"))
    assert payload["candidate_analysis"]["recommended_candidate_id"] == "threshold_0_3"
    assert len(payload["candidate_analysis"]["candidates"]) == 2
    assert (tmp_path / "job" / "stems" / "no_drums.wav").exists()
    assert result.artifacts["musicxml"].exists()
    assert result.artifacts["musicxml"].parent == tmp_path / "job" / "candidates" / "threshold_0_3" / "notation"


def test_candidate_analysis_keeps_a_canonical_artifact_without_recommending_hard_rejected_candidates(tmp_path, monkeypatch) -> None:
    input_path = tmp_path / "input.wav"
    _write_wav(input_path)

    def write(path, content=b"artifact"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def preprocess(_self, _artifacts, output_dir):
        return {"normalized_audio": write(output_dir / "audio" / "normalized.wav")}, {"duration_seconds": 8.0}

    def separate(_self, _artifacts, output_dir):
        return {"drums_stem": write(output_dir / "stems" / "drums.wav")}, {"accompaniment_available": False}

    def transcribe(_self, _artifacts, output_dir):
        return {"raw_midi": write(output_dir / "midi" / "raw_drum.mid")}, {"event_count": 12}

    def postprocess(_self, _artifacts, output_dir):
        return {
            "processed_midi": write(output_dir / "midi" / "processed_drum.mid"),
            "drum_events": write(output_dir / "midi" / "drum_events.json", b"{}"),
        }, {
            "input_event_count": 12,
            "output_event_count": 12,
            "processed_drum_counts": {"kick": 3, "snare": 3, "closed_hat": 6},
            "quality_flags": ["too_few_events"],
            "warnings": ["too_few_events"],
        }

    def notation(_self, _artifacts, output_dir):
        return {
            "musicxml": write(output_dir / "notation" / "score.musicxml"),
            "performance_midi": write(output_dir / "notation" / "performance_score.mid"),
            "chart_events": write(output_dir / "notation" / "chart_events.json", b"{}"),
        }, {
            "validation": {"musicxml": {"available": True, "parseable": True, "warnings": []}},
            "readability": {"dense_measure_count": 0},
            "performance_gate": {"verdict": "playable_but_low_confidence"},
        }

    monkeypatch.setattr(LocalPipelineRunner, "_run_audio_preprocessing", preprocess)
    monkeypatch.setattr(LocalPipelineRunner, "_run_source_separation", separate)
    monkeypatch.setattr(LocalPipelineRunner, "_run_drum_transcription", transcribe)
    monkeypatch.setattr(LocalPipelineRunner, "_run_midi_post_processing", postprocess)
    monkeypatch.setattr(LocalPipelineRunner, "_run_notation_generation", notation)

    result = LocalPipelineRunner(LocalPipelineConfig(candidate_thresholds=(0.3, 0.4))).run(input_path, tmp_path / "job")

    payload = json.loads(result.log_path.read_text(encoding="utf-8"))
    analysis = payload["candidate_analysis"]
    assert result.status == "completed"
    assert analysis["recommended_candidate_id"] is None
    assert analysis["canonical_candidate_id"] == "threshold_0_3"
    assert [candidate.get("rank") for candidate in analysis["candidates"]] == [None, None]
    assert [candidate["selected"] for candidate in analysis["candidates"]] == [True, False]


def test_candidate_analysis_records_separated_preset_as_a_distinct_strategy(tmp_path, monkeypatch) -> None:
    input_path = tmp_path / "input.wav"
    _write_wav(input_path)
    transcriber_configs: list[tuple[float, str | None]] = []

    def write(path, content=b"artifact"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def preprocess(_self, _artifacts, output_dir):
        return {"normalized_audio": write(output_dir / "audio" / "normalized.wav")}, {}

    def separate(_self, _artifacts, output_dir):
        return {"drums_stem": write(output_dir / "stems" / "drums.wav")}, {}

    def transcribe(self, _artifacts, output_dir):
        transcriber_configs.append((self.config.adtof_threshold, self.config.adtof_threshold_preset))
        return {"raw_midi": write(output_dir / "midi" / "raw_drum.mid")}, {}

    def postprocess(_self, _artifacts, output_dir):
        return {"processed_midi": write(output_dir / "midi" / "processed.mid"), "drum_events": write(output_dir / "midi" / "events.json", b"{}")}, {"input_event_count": 12, "output_event_count": 12, "processed_drum_counts": {"kick": 3, "snare": 3, "closed_hat": 6}, "quality_flags": [], "warnings": []}

    def notation(_self, _artifacts, output_dir):
        return {"musicxml": write(output_dir / "notation" / "score.musicxml"), "performance_midi": write(output_dir / "notation" / "performance_score.mid"), "chart_events": write(output_dir / "notation" / "chart_events.json", b"{}")}, {"validation": {"musicxml": {"available": True, "parseable": True, "warnings": []}}, "readability": {"dense_measure_count": 0}, "performance_gate": {"verdict": "playable_but_low_confidence"}}

    monkeypatch.setattr(LocalPipelineRunner, "_run_audio_preprocessing", preprocess)
    monkeypatch.setattr(LocalPipelineRunner, "_run_source_separation", separate)
    monkeypatch.setattr(LocalPipelineRunner, "_run_drum_transcription", transcribe)
    monkeypatch.setattr(LocalPipelineRunner, "_run_midi_post_processing", postprocess)
    monkeypatch.setattr(LocalPipelineRunner, "_run_notation_generation", notation)

    result = LocalPipelineRunner(LocalPipelineConfig(candidate_thresholds=(0.4,), candidate_threshold_presets=("separated_v1",))).run(input_path, tmp_path / "job")

    analysis = json.loads(result.log_path.read_text(encoding="utf-8"))["candidate_analysis"]
    assert result.status == "completed"
    assert transcriber_configs == [(0.4, None), (0.5, "separated_v1")]
    assert analysis["strategy_profile"] == {"schema_version": "1.0", "families": ["scalar_threshold_v1", "adtof_preset_v1"]}
    assert [(candidate["candidate_id"], candidate["config"]["strategy"], candidate["config"]["threshold"]) for candidate in analysis["candidates"]] == [
        ("threshold_0_4", "scalar_threshold_v1", 0.4),
        ("preset_separated_v1", "adtof_preset_v1", None),
    ]
