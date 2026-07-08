from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent
import scripts.run_true_ai_quality_matrix as quality_matrix
from scripts.run_true_ai_quality_matrix import QualityMatrixConfig, run_quality_matrix


def _config(tmp_path: Path, *, fixtures: tuple[Path, ...] | None = None, external_fixture: Path | None = None) -> QualityMatrixConfig:
    return QualityMatrixConfig(
        fixtures=(Path("tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav"),)
        if fixtures is None
        else fixtures,
        output_dir=tmp_path,
        thresholds=("0.3", "0.5"),
        ai_python=sys.executable,
        demucs_device="cpu",
        adtof_command_template="python -m adtof transcribe --input {input} --output {output}",
        adtof_checkpoint=None,
        adtof_device="cpu",
        timeout_seconds=60,
        external_fixture=external_fixture,
        export_pdf=False,
    )


def test_quality_matrix_writes_blocked_report_when_true_ai_runtime_is_not_ready(tmp_path: Path) -> None:
    def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        assert _has_command(command, "check_ai_runtime.py")
        return subprocess.CompletedProcess(command, 0, json.dumps(_preflight_payload(true_ai_ready=False)), "")

    report = run_quality_matrix(
        _config(tmp_path),
        process_runner=fake_runner,
        checked_at=datetime(2026, 7, 7, tzinfo=UTC),
    )

    assert report["status"] == "blocked"
    assert report["summary"]["blocked_runs"] == 2
    assert report["fixtures"][0]["status"] == "blocked"
    assert report["fixtures"][0]["runs"][0]["blocked_reason"]
    assert report["redaction"]["status"] == "passed"
    assert "/tmp/" not in json.dumps(report)
    assert "/Users/" not in json.dumps(report)


def test_quality_matrix_skips_missing_external_fixture_without_local_path(tmp_path: Path) -> None:
    report = run_quality_matrix(
        _config(tmp_path, fixtures=(), external_fixture=tmp_path / "missing-real-drum.wav"),
        process_runner=lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, "", ""),
        checked_at=datetime(2026, 7, 7, tzinfo=UTC),
    )

    assert report["status"] == "skipped"
    assert report["summary"]["skipped_fixtures"] == 1
    assert report["fixtures"][0] == {
        "fixture": "external:missing-real-drum.wav",
        "source": "external",
        "status": "skipped",
        "reason": "external_fixture_missing",
        "runs": [],
    }
    assert "/tmp/" not in json.dumps(report)


def test_quality_matrix_summarizes_completed_threshold_candidates(tmp_path: Path) -> None:
    def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if _has_command(command, "check_ai_runtime.py"):
            return subprocess.CompletedProcess(command, 0, json.dumps(_preflight_payload(true_ai_ready=True)), "")
        assert _has_command(command, "run_local_pipeline.py")
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_pipeline_artifacts(output_dir, events=_usable_groove_events())
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    report = run_quality_matrix(
        _config(tmp_path, fixtures=(Path("tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav"),)),
        process_runner=fake_runner,
        checked_at=datetime(2026, 7, 7, tzinfo=UTC),
    )

    assert report["status"] == "completed"
    assert report["summary"]["completed_runs"] == 2
    assert report["summary"]["candidate_thresholds"]
    first_run = report["fixtures"][0]["runs"][0]
    assert first_run["minimum_gate"]["status"] == "passed"
    assert first_run["processed_event_count"] == 8
    assert first_run["processed_drum_counts"] == {"closed_hat": 4, "kick": 2, "snare": 2}
    assert first_run["minimum_gate"]["musicxml_parseable"] is True
    assert "mostly_tom_output" not in first_run["quality_flags"]
    assert first_run["musicxml"]["available"] is True
    assert first_run["musicxml"]["parseable"] is True
    assert "/tmp/" not in json.dumps(report)
    assert "command_template" not in json.dumps(report)


def test_quality_matrix_rejects_two_event_smoke_output_as_candidate(tmp_path: Path) -> None:
    def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if _has_command(command, "check_ai_runtime.py"):
            return subprocess.CompletedProcess(command, 0, json.dumps(_preflight_payload(true_ai_ready=True)), "")
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_pipeline_artifacts(output_dir, events=_two_event_kick_snare_events())
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    report = run_quality_matrix(
        _config(tmp_path, fixtures=(Path("tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav"),)),
        process_runner=fake_runner,
        checked_at=datetime(2026, 7, 7, tzinfo=UTC),
    )

    first_run = report["fixtures"][0]["runs"][0]
    assert report["summary"]["candidate_thresholds"] == []
    assert first_run["minimum_gate"]["status"] == "failed"
    assert first_run["minimum_gate"]["event_count_sufficient"] is False
    assert first_run["minimum_gate"]["blocking_flags"] == ["no_usable_groove", "sparse_transcription", "too_few_events"]
    assert {"no_usable_groove", "sparse_transcription", "too_few_events"} <= set(first_run["quality_flags"])


def test_quality_matrix_rejects_unparseable_musicxml_as_candidate(tmp_path: Path) -> None:
    def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if _has_command(command, "check_ai_runtime.py"):
            return subprocess.CompletedProcess(command, 0, json.dumps(_preflight_payload(true_ai_ready=True)), "")
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_pipeline_artifacts(output_dir, events=_usable_groove_events(), musicxml_text="not xml")
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    report = run_quality_matrix(
        _config(tmp_path, fixtures=(Path("tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav"),)),
        process_runner=fake_runner,
        checked_at=datetime(2026, 7, 7, tzinfo=UTC),
    )

    first_run = report["fixtures"][0]["runs"][0]
    assert report["summary"]["candidate_thresholds"] == []
    assert first_run["musicxml"]["available"] is True
    assert first_run["musicxml"]["parseable"] is False
    assert first_run["minimum_gate"]["status"] == "failed"
    assert first_run["minimum_gate"]["musicxml_parseable"] is False


def test_quality_matrix_rejects_mostly_tom_output_as_candidate(tmp_path: Path) -> None:
    def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if _has_command(command, "check_ai_runtime.py"):
            return subprocess.CompletedProcess(command, 0, json.dumps(_preflight_payload(true_ai_ready=True)), "")
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_pipeline_artifacts(output_dir, events=_usable_groove_events(), warnings=["mostly_tom_output"])
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    report = run_quality_matrix(
        _config(tmp_path, fixtures=(Path("tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav"),)),
        process_runner=fake_runner,
        checked_at=datetime(2026, 7, 7, tzinfo=UTC),
    )

    first_run = report["fixtures"][0]["runs"][0]
    assert report["summary"]["candidate_thresholds"] == []
    assert first_run["minimum_gate"]["status"] == "failed"
    assert first_run["minimum_gate"]["blocking_flags"] == ["mostly_tom_output"]
    assert "mostly_tom_output" in first_run["quality_flags"]


def test_quality_matrix_rejects_no_snare_detected_as_candidate(tmp_path: Path) -> None:
    def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if _has_command(command, "check_ai_runtime.py"):
            return subprocess.CompletedProcess(command, 0, json.dumps(_preflight_payload(true_ai_ready=True)), "")
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_pipeline_artifacts(
            output_dir,
            events=_no_snare_events(),
        )
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    report = run_quality_matrix(
        _config(tmp_path, fixtures=(Path("tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav"),)),
        process_runner=fake_runner,
        checked_at=datetime(2026, 7, 7, tzinfo=UTC),
    )

    first_run = report["fixtures"][0]["runs"][0]
    assert report["summary"]["candidate_thresholds"] == []
    assert first_run["minimum_gate"]["status"] == "failed"
    assert first_run["minimum_gate"]["snare_present"] is False
    assert first_run["minimum_gate"]["blocking_flags"] == ["no_snare_detected"]
    assert "no_snare_detected" in first_run["quality_flags"]


def test_quality_matrix_rejects_unavailable_musicxml_as_candidate(tmp_path: Path) -> None:
    def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if _has_command(command, "check_ai_runtime.py"):
            return subprocess.CompletedProcess(command, 0, json.dumps(_preflight_payload(true_ai_ready=True)), "")
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_pipeline_artifacts(output_dir, events=_usable_groove_events(), musicxml_available=False)
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    report = run_quality_matrix(
        _config(tmp_path, fixtures=(Path("tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav"),)),
        process_runner=fake_runner,
        checked_at=datetime(2026, 7, 7, tzinfo=UTC),
    )

    first_run = report["fixtures"][0]["runs"][0]
    assert report["summary"]["candidate_thresholds"] == []
    assert first_run["musicxml"]["available"] is False
    assert first_run["musicxml"]["parseable"] is False
    assert first_run["minimum_gate"]["status"] == "failed"
    assert first_run["minimum_gate"]["musicxml_available"] is False


def test_quality_matrix_stdout_does_not_print_absolute_paths_or_command_template(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    def fake_run_quality_matrix(_config: QualityMatrixConfig) -> dict:
        return {"status": "blocked", "output_dir_name": tmp_path.name}

    monkeypatch.setattr(quality_matrix, "run_quality_matrix", fake_run_quality_matrix)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_true_ai_quality_matrix.py",
            "--output-dir",
            str(tmp_path),
            "--adtof-command-template",
            "python -m adtof transcribe --input {input} --output {output}",
        ],
    )

    assert quality_matrix.main() == 0
    stdout = capsys.readouterr().out
    assert "/tmp/" not in stdout
    assert "/Users/" not in stdout
    assert "command_template" not in stdout
    assert "matrix_report_name" in stdout
    assert "matrix_report.json" in stdout


def _preflight_payload(*, true_ai_ready: bool) -> dict:
    return {
        "python": {"version": "3.11.15"},
        "runtime_checks": {
            "local_pipeline": {
                "mock_ai_ready": True,
                "true_ai_ready": true_ai_ready,
                "missing_requirements": [] if true_ai_ready else ["ADTOF runtime is not ready"],
            },
            "adtof_pytorch": {
                "status_code": "ready" if true_ai_ready else "verify_input_missing",
                "output_verification": {"event_count": 2 if true_ai_ready else None},
            },
        },
    }


def _write_pipeline_artifacts(
    output_dir: Path,
    *,
    events: tuple[ProcessedDrumEvent, ...],
    musicxml_text: str = "<score-partwise />",
    musicxml_available: bool = True,
    processed_drum_counts: dict[str, int] | None = None,
    warnings: list[str] | None = None,
) -> None:
    (output_dir / "audio").mkdir(parents=True)
    (output_dir / "stems").mkdir()
    (output_dir / "midi").mkdir()
    (output_dir / "notation").mkdir()
    (output_dir / "logs").mkdir()
    (output_dir / "audio" / "normalized.wav").write_bytes(b"wav")
    (output_dir / "stems" / "drums.wav").write_bytes(b"drums")
    write_drum_midi(output_dir / "midi" / "raw_drum.mid", events, ticks_per_beat=480)
    write_drum_midi(output_dir / "midi" / "processed_drum.mid", events, ticks_per_beat=480)
    (output_dir / "midi" / "drum_events.json").write_text(
        json.dumps(
            {
                "event_count": len(events),
                "raw_note_histogram": _note_histogram(events),
                "processed_drum_counts": processed_drum_counts
                if processed_drum_counts is not None
                else _processed_drum_counts(events),
                "warnings": ["hihat_missing_likely"] if warnings is None else warnings,
            }
        ),
        encoding="utf-8",
    )
    if musicxml_available:
        (output_dir / "notation" / "score.musicxml").write_text(musicxml_text, encoding="utf-8")
    (output_dir / "logs" / "pipeline.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "stages": [
                    {
                        "name": "midi_post_processing",
                        "status": "completed",
                        "report": {"warnings": ["hihat_missing_likely"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _has_command(command: list[str], name: str) -> bool:
    return any(item.endswith(name) for item in command)


def _two_event_kick_snare_events() -> tuple[ProcessedDrumEvent, ...]:
    return (
        ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=90),
    )


def _usable_groove_events() -> tuple[ProcessedDrumEvent, ...]:
    return (
        ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=240, note=42, drum="closed_hat", velocity=70),
        ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=90),
        ProcessedDrumEvent(tick=720, note=42, drum="closed_hat", velocity=70),
        ProcessedDrumEvent(tick=960, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=1200, note=42, drum="closed_hat", velocity=70),
        ProcessedDrumEvent(tick=1440, note=38, drum="snare", velocity=90),
        ProcessedDrumEvent(tick=1680, note=42, drum="closed_hat", velocity=70),
    )


def _no_snare_events() -> tuple[ProcessedDrumEvent, ...]:
    return (
        ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=240, note=42, drum="closed_hat", velocity=70),
        ProcessedDrumEvent(tick=480, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=720, note=42, drum="closed_hat", velocity=70),
        ProcessedDrumEvent(tick=960, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=1200, note=42, drum="closed_hat", velocity=70),
        ProcessedDrumEvent(tick=1440, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=1680, note=42, drum="closed_hat", velocity=70),
    )


def _note_histogram(events: tuple[ProcessedDrumEvent, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        key = str(event.note)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _processed_drum_counts(events: tuple[ProcessedDrumEvent, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        counts[event.drum] = counts.get(event.drum, 0) + 1
    return counts
