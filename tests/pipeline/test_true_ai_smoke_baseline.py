from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import ProcessedDrumEvent
from scripts.run_true_ai_smoke_baseline import BaselineConfig, run_baseline


def _config(tmp_path: Path) -> BaselineConfig:
    return BaselineConfig(
        input_path=Path("tests/pipeline/fixtures/audio/synthetic_clean_drum_pattern.wav"),
        output_root=tmp_path,
        run_id="baseline-test",
        ai_python=sys.executable,
        demucs_device="cpu",
        adtof_command_template="python -m adtof transcribe --input {input} --output {output}",
        adtof_checkpoint=None,
        adtof_device="cpu",
        adtof_threshold="0.5",
        timeout_seconds=60,
    )


def test_true_ai_baseline_writes_blocked_report_when_runtime_is_degraded(tmp_path: Path) -> None:
    def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        assert _has_command(command, "check_ai_runtime.py")
        return subprocess.CompletedProcess(command, 0, json.dumps(_preflight_payload(true_ai_ready=False)), "")

    result = run_baseline(
        _config(tmp_path),
        process_runner=fake_runner,
        checked_at=datetime(2026, 7, 3, tzinfo=UTC),
    )

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.status == "blocked"
    assert result.return_code == 0
    assert report["status"] == "blocked"
    assert report["baseline_ref"] == "baseline:baseline-test"
    assert "ADTOF runtime has not produced" in report["blocked_reason"]
    assert report["preflight"]["adtof_offline_ready"] is False
    assert report["preflight"]["adtof_status_code"] == "verify_input_missing"
    assert "/Users/" not in json.dumps(report)
    assert "/tmp/" not in json.dumps(report)


def test_true_ai_baseline_writes_completed_artifact_inspection(tmp_path: Path) -> None:
    def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if _has_command(command, "check_ai_runtime.py"):
            return subprocess.CompletedProcess(command, 0, json.dumps(_preflight_payload(true_ai_ready=True)), "")
        assert _has_command(command, "run_local_pipeline.py")
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_pipeline_artifacts(output_dir)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"status": "completed", "failed_stage": None, "output_dir": str(output_dir)}),
            "",
        )

    result = run_baseline(
        _config(tmp_path),
        process_runner=fake_runner,
        checked_at=datetime(2026, 7, 3, tzinfo=UTC),
    )

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.status == "completed"
    assert result.return_code == 0
    assert report["status"] == "completed"
    assert report["baseline_ref"] == "baseline:baseline-test"
    assert report["artifacts"]["raw_midi"]["path"] == "midi/raw_drum.mid"
    assert report["artifacts"]["musicxml"]["available"] is True
    assert report["exports"]["pdf"] == {"status": "unavailable", "optional": True, "file_size_bytes": None}
    assert report["validation"]["musicxml"]["available"] is True
    assert report["validation"]["musicxml"]["parseable"] is True
    assert "musicxml_version_missing" in report["validation"]["musicxml"]["warnings"]
    assert report["validation"]["pdf"]["error_code"] == "pdf_unavailable"
    assert report["inspection"]["raw_midi"]["event_count"] == 2
    assert report["inspection"]["raw_midi"]["note_histogram"] == {"36": 1, "38": 1}
    assert report["inspection"]["drum_events"]["processed_drum_counts"] == {"kick": 1, "snare": 1}
    assert report["quality"]["raw_event_count"] == 2
    assert report["quality"]["processed_event_count"] == 2
    assert "hihat_missing_likely" in report["quality"]["quality_flags"]
    assert "pdf_optional_unavailable" in report["quality"]["warnings"]
    assert report["pipeline"]["warnings"] == ["hihat_missing_likely"]


def test_true_ai_baseline_preserves_zero_processed_event_count(tmp_path: Path) -> None:
    def fake_runner(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        if _has_command(command, "check_ai_runtime.py"):
            return subprocess.CompletedProcess(command, 0, json.dumps(_preflight_payload(true_ai_ready=True)), "")
        assert _has_command(command, "run_local_pipeline.py")
        output_dir = Path(command[command.index("--output-dir") + 1])
        _write_pipeline_artifacts_with_empty_processed_midi(output_dir)
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    result = run_baseline(
        _config(tmp_path),
        process_runner=fake_runner,
        checked_at=datetime(2026, 7, 3, tzinfo=UTC),
    )

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.status == "completed"
    assert report["inspection"]["processed_midi"]["event_count"] == 0
    assert report["inspection"]["drum_events"]["event_count"] == 2
    assert report["quality"]["processed_event_count"] == 0
    assert report["quality"]["processed_drum_counts"] == {}
    assert "no_usable_groove" in report["quality"]["quality_flags"]
    assert "too_few_events" in report["quality"]["quality_flags"]


def _preflight_payload(*, true_ai_ready: bool) -> dict:
    return {
        "python": {"version": "3.11.15"},
        "runtime_checks": {
            "local_pipeline": {
                "demo_mock_ready": True,
                "generic_baseline_ready": True,
                "missing_requirements": []
                if true_ai_ready
                else [
                    "ADTOF runtime has not produced and verified raw_drum.mid; "
                    "set GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE and GROOVESCRIBE_ADTOF_VERIFY_INPUT "
                    "for output verification"
                ],
            },
            "adtof_pytorch": {
                "ready": true_ai_ready,
                "status_code": "ready" if true_ai_ready else "verify_input_missing",
                "output_verification": {"event_count": 2 if true_ai_ready else None},
            },
        },
    }


def _has_command(command: list[str], name: str) -> bool:
    return any(item.endswith(name) for item in command)


def _write_pipeline_artifacts(output_dir: Path) -> None:
    (output_dir / "audio").mkdir(parents=True)
    (output_dir / "stems").mkdir()
    (output_dir / "midi").mkdir()
    (output_dir / "notation").mkdir()
    (output_dir / "logs").mkdir()
    (output_dir / "audio" / "normalized.wav").write_bytes(b"wav")
    (output_dir / "stems" / "drums.wav").write_bytes(b"drums")
    events = (
        ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=90),
    )
    write_drum_midi(output_dir / "midi" / "raw_drum.mid", events, ticks_per_beat=480)
    write_drum_midi(output_dir / "midi" / "processed_drum.mid", events, ticks_per_beat=480)
    (output_dir / "midi" / "drum_events.json").write_text(
        json.dumps(
            {
                "event_count": 2,
                "raw_note_histogram": {"36": 1, "38": 1},
                "processed_drum_counts": {"kick": 1, "snare": 1},
                "warnings": ["hihat_missing_likely"],
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "notation" / "score.musicxml").write_text("<score-partwise />", encoding="utf-8")
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


def _write_pipeline_artifacts_with_empty_processed_midi(output_dir: Path) -> None:
    (output_dir / "audio").mkdir(parents=True)
    (output_dir / "stems").mkdir()
    (output_dir / "midi").mkdir()
    (output_dir / "notation").mkdir()
    (output_dir / "logs").mkdir()
    (output_dir / "audio" / "normalized.wav").write_bytes(b"wav")
    (output_dir / "stems" / "drums.wav").write_bytes(b"drums")
    raw_events = (
        ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=100),
        ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=90),
    )
    write_drum_midi(output_dir / "midi" / "raw_drum.mid", raw_events, ticks_per_beat=480)
    write_drum_midi(output_dir / "midi" / "processed_drum.mid", (), ticks_per_beat=480)
    (output_dir / "midi" / "drum_events.json").write_text(
        json.dumps(
            {
                "event_count": 2,
                "raw_note_histogram": {"36": 1, "38": 1},
                "processed_drum_counts": {"kick": 1, "snare": 1},
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "notation" / "score.musicxml").write_text("<score-partwise />", encoding="utf-8")
    (output_dir / "logs" / "pipeline.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "stages": [
                    {
                        "name": "midi_post_processing",
                        "status": "completed",
                        "report": {"warnings": []},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
