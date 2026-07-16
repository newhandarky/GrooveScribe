from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.check_v1_true_ai_setup import check_true_ai_setup
    from scripts.redaction import find_unsafe_tokens
    from scripts.run_true_ai_quality_matrix import QualityMatrixConfig, run_quality_matrix
    from scripts.run_true_ai_v1_eval import V1EvalConfig, run_v1_eval
    from scripts.true_ai_runtime_defaults import (
        DEFAULT_ADTOF_DEVICE,
        DEFAULT_ADTOF_THRESHOLD,
        DEFAULT_ADTOF_VERIFY_INPUT,
        DEFAULT_ADTOF_VERIFY_OUTPUT_DIR,
        DEFAULT_DEMUCS_DEVICE,
        DEFAULT_THRESHOLD_MATRIX,
        DEFAULT_THRESHOLD_PRESET,
        DEFAULT_TOM_FILTER_PRESET,
        default_adtof_command_template,
        public_env_summary,
        true_ai_runtime_env,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from check_v1_true_ai_setup import check_true_ai_setup
    from redaction import find_unsafe_tokens
    from run_true_ai_quality_matrix import QualityMatrixConfig, run_quality_matrix
    from run_true_ai_v1_eval import V1EvalConfig, run_v1_eval
    from true_ai_runtime_defaults import (
        DEFAULT_ADTOF_DEVICE,
        DEFAULT_ADTOF_THRESHOLD,
        DEFAULT_ADTOF_VERIFY_INPUT,
        DEFAULT_ADTOF_VERIFY_OUTPUT_DIR,
        DEFAULT_DEMUCS_DEVICE,
        DEFAULT_THRESHOLD_MATRIX,
        DEFAULT_THRESHOLD_PRESET,
        DEFAULT_TOM_FILTER_PRESET,
        default_adtof_command_template,
        public_env_summary,
        true_ai_runtime_env,
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("/tmp/groovescribe-v1-real-audio-pilot")
REPORT_FILENAME = "pilot_report.json"
HANDOFF_FILENAME = "pilot_handoff.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a V1 true-AI pilot against one authorized real audio file.")
    parser.add_argument("--input", required=True, type=Path, help="Authorized WAV/MP3 audio file to evaluate locally.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--ai-python", default=os.environ.get("AI_PYTHON", ".venv-ai/bin/python"))
    parser.add_argument("--adtof-command-template", default=os.environ.get("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"))
    parser.add_argument("--adtof-verify-input", type=Path, default=DEFAULT_ADTOF_VERIFY_INPUT)
    parser.add_argument("--adtof-verify-output-dir", type=Path, default=DEFAULT_ADTOF_VERIFY_OUTPUT_DIR)
    parser.add_argument("--demucs-device", default=os.environ.get("GROOVESCRIBE_DEMUCS_DEVICE", DEFAULT_DEMUCS_DEVICE))
    parser.add_argument("--adtof-device", default=os.environ.get("GROOVESCRIBE_ADTOF_DEVICE", DEFAULT_ADTOF_DEVICE))
    parser.add_argument("--adtof-threshold", default=os.environ.get("GROOVESCRIBE_ADTOF_THRESHOLD", DEFAULT_ADTOF_THRESHOLD))
    parser.add_argument("--thresholds", default=",".join(DEFAULT_THRESHOLD_MATRIX))
    parser.add_argument("--skip-quality-matrix", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("PIPELINE_TRUE_AI_TIMEOUT_SECONDS", "3600")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if _inside_repo(args.output_dir):
        print(json.dumps(_failure("output_dir_must_be_outside_repo"), ensure_ascii=False, indent=2))
        return 2
    report = run_real_audio_pilot(
        input_path=args.input,
        output_dir=args.output_dir,
        ai_python=args.ai_python,
        adtof_command_template=args.adtof_command_template,
        verify_input=args.adtof_verify_input,
        verify_output_dir=args.adtof_verify_output_dir,
        demucs_device=args.demucs_device,
        adtof_device=args.adtof_device,
        adtof_threshold=args.adtof_threshold,
        thresholds=_parse_thresholds(args.thresholds),
        skip_quality_matrix=args.skip_quality_matrix,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                "schema_version": "1.0",
                "status": report["status"],
                "report": REPORT_FILENAME,
                "handoff": HANDOFF_FILENAME,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "completed" else 1


def run_real_audio_pilot(
    *,
    input_path: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    ai_python: str = ".venv-ai/bin/python",
    adtof_command_template: str | None = None,
    verify_input: Path = DEFAULT_ADTOF_VERIFY_INPUT,
    verify_output_dir: Path = DEFAULT_ADTOF_VERIFY_OUTPUT_DIR,
    demucs_device: str = DEFAULT_DEMUCS_DEVICE,
    adtof_device: str = DEFAULT_ADTOF_DEVICE,
    adtof_threshold: str = DEFAULT_ADTOF_THRESHOLD,
    thresholds: tuple[str, ...] = DEFAULT_THRESHOLD_MATRIX,
    skip_quality_matrix: bool = False,
    timeout_seconds: int = 3600,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    if _inside_repo(output_dir):
        raise ValueError("output_dir_must_be_outside_repo")
    checked = checked_at or datetime.now(UTC)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_input = input_path.expanduser()
    runtime_env = true_ai_runtime_env(
        adtof_command_template=adtof_command_template or default_adtof_command_template(),
        verify_input=verify_input,
        verify_output_dir=verify_output_dir,
        demucs_device=demucs_device,
        adtof_device=adtof_device,
        adtof_threshold=adtof_threshold,
    )

    if not resolved_input.exists():
        report = _finalize(
            {
                "schema_version": "1.0",
                "status": "blocked",
                "checked_at": checked.isoformat(),
                "input": _input_summary(resolved_input),
                "runtime": {"status": "not_checked"},
                "env": public_env_summary(runtime_env),
                "v1_eval": {"status": "skipped"},
                "quality_matrix": {"status": "skipped"},
                "manual_eval_seed": {"status": "blocked", "blocked_reason": "input_file_missing"},
                "review_packet": {"status": "requires_completed_backend_job"},
                "next_steps": ["Provide an authorized local WAV or MP3 file with --input."],
            }
        )
        _write_outputs(output_dir, report)
        return report

    if find_unsafe_tokens(resolved_input.name):
        report = _finalize(
            {
                "schema_version": "1.0",
                "status": "failed",
                "checked_at": checked.isoformat(),
                "input": {"ref": "external:redacted", "exists": True, "suffix": resolved_input.suffix.lower()},
                "runtime": {"status": "not_checked"},
                "env": public_env_summary(runtime_env),
                "v1_eval": {"status": "skipped"},
                "quality_matrix": {"status": "skipped"},
                "manual_eval_seed": {"status": "blocked", "blocked_reason": "unsafe_input_filename"},
                "review_packet": {"status": "requires_completed_backend_job"},
                "next_steps": ["Rename the authorized audio file with a public-safe filename and rerun the pilot."],
            }
        )
        _write_outputs(output_dir, report)
        return report

    setup = check_true_ai_setup(
        ai_python=ai_python,
        adtof_command_template=runtime_env["GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"],
        verify_input=verify_input,
        verify_output_dir=verify_output_dir,
        demucs_device=demucs_device,
        adtof_device=adtof_device,
        adtof_threshold=adtof_threshold,
        checked_at=checked,
    )

    eval_dir = output_dir / "v1_eval"
    v1_eval = run_v1_eval(
        V1EvalConfig(
            output_dir=eval_dir,
            wav_fixture=REPO_ROOT / "tests" / "pipeline" / "fixtures" / "audio" / "synthetic_separated_kick_snare_hat_pattern.wav",
            external_fixture=resolved_input,
            ai_python=ai_python,
            demucs_device=demucs_device,
            adtof_command_template=runtime_env["GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"],
            adtof_checkpoint=os.environ.get("GROOVESCRIBE_ADTOF_CHECKPOINT"),
            adtof_device=adtof_device,
            scalar_threshold=adtof_threshold,
            threshold_preset=DEFAULT_THRESHOLD_PRESET,
            tom_filter_preset=DEFAULT_TOM_FILTER_PRESET,
            timeout_seconds=timeout_seconds,
        ),
        checked_at=checked,
    )

    matrix = {"status": "skipped", "reason": "skip_quality_matrix"} if skip_quality_matrix else run_quality_matrix(
        QualityMatrixConfig(
            fixtures=(),
            output_dir=output_dir / "quality_matrix",
            thresholds=thresholds,
            ai_python=ai_python,
            demucs_device=demucs_device,
            adtof_command_template=runtime_env["GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"],
            adtof_checkpoint=os.environ.get("GROOVESCRIBE_ADTOF_CHECKPOINT"),
            adtof_device=adtof_device,
            timeout_seconds=timeout_seconds,
            adtof_threshold_preset=DEFAULT_THRESHOLD_PRESET,
            tom_filter_preset=DEFAULT_TOM_FILTER_PRESET,
            external_fixture=resolved_input,
            export_pdf=True,
        ),
        checked_at=checked,
    )

    real_rows = _external_rows(v1_eval)
    best_row = _best_real_row(real_rows)
    status = _pilot_status(setup, best_row)
    report = _finalize(
        {
            "schema_version": "1.0",
            "status": status,
            "checked_at": checked.isoformat(),
            "input": _input_summary(resolved_input),
            "runtime": {
                "status": setup.get("status"),
                "true_ai_ready": setup.get("true_ai_ready"),
                "missing_requirements": setup.get("missing_requirements", []),
            },
            "env": public_env_summary(runtime_env),
            "v1_eval": _v1_eval_summary(v1_eval, best_row),
            "quality_matrix": _matrix_summary(matrix),
            "manual_eval_seed": _manual_eval_seed(best_row),
            "review_packet": {
                "status": "requires_completed_backend_job",
                "note": "Use the result page review packet actions after uploading this audio with True-AI preset.",
            },
            "next_steps": _pilot_next_steps(status, best_row, matrix),
        }
    )
    _write_outputs(output_dir, report)
    return report


def _pilot_status(setup: dict[str, Any], best_row: dict[str, Any] | None) -> str:
    if setup.get("status") != "ready":
        return "blocked"
    if best_row and best_row.get("human_correctable") is True:
        return "completed"
    return "completed_with_blockers"


def _v1_eval_summary(v1_eval: dict[str, Any], best_row: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "status": v1_eval.get("status"),
        "report_ref": "v1_eval/v1_eval_report.json",
        "external_fixture_count": _dict(v1_eval.get("v1_readiness")).get("external_fixture_count", 0),
        "external_human_correctable_count": _dict(v1_eval.get("v1_readiness")).get("external_human_correctable_count", 0),
        "best_real_audio": _row_summary(best_row),
    }


def _row_summary(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"status": "not_available"}
    verdict = _dict(row.get("quality_verdict"))
    return {
        "status": row.get("status"),
        "human_correctable": bool(row.get("human_correctable")),
        "primary_blocker": row.get("primary_blocker"),
        "raw_event_count": row.get("raw_event_count"),
        "processed_event_count": row.get("processed_event_count"),
        "drum_counts": _dict(row.get("processed_drum_counts")),
        "quality_flags": _list(verdict.get("limitations")) or _list(row.get("quality_flags")),
        "performance_gate": _dict(verdict.get("candidate_gate")),
        "musicxml": _dict(row.get("musicxml")),
        "pdf": {"optional": True, "status": "not_blocking"},
        "baseline_ref": row.get("manual_eval_seed", {}).get("artifact_ref"),
        "baseline_report_ref": row.get("manual_eval_seed", {}).get("baseline_report_ref"),
    }


def _matrix_summary(matrix: dict[str, Any]) -> dict[str, Any]:
    summary = _dict(matrix.get("summary"))
    return {
        "status": matrix.get("status"),
        "report_ref": "quality_matrix/matrix_report.json" if matrix.get("status") != "skipped" else None,
        "thresholds": matrix.get("thresholds", []),
        "candidate_thresholds": summary.get("candidate_thresholds", []),
        "completed_runs": summary.get("completed_runs"),
        "blocked_runs": summary.get("blocked_runs"),
    }


def _manual_eval_seed(best_row: dict[str, Any] | None) -> dict[str, Any]:
    if not best_row:
        return {"status": "blocked", "blocked_reason": "no_real_audio_row"}
    seed = _dict(best_row.get("manual_eval_seed"))
    return {
        "status": "ready",
        "artifact_ref": seed.get("artifact_ref"),
        "baseline_report_ref": seed.get("baseline_report_ref"),
        "human_correctable": "",
        "primary_blocker": best_row.get("primary_blocker") or "",
        "review_notes_ref": "",
    }


def _pilot_next_steps(status: str, best_row: dict[str, Any] | None, matrix: dict[str, Any]) -> list[str]:
    if status == "blocked":
        return ["Run npm run check:true-ai and fix the reported runtime blocker."]
    if best_row and best_row.get("human_correctable") is True:
        return ["Open the result page review packet and fill manual eval scores with human review."]
    blocker = best_row.get("primary_blocker") if best_row else "no_real_audio_row"
    steps = [f"Treat this pilot as blocked by {blocker}."]
    candidates = _dict(matrix.get("summary")).get("candidate_thresholds") if isinstance(matrix, dict) else None
    if candidates:
        steps.append("Compare candidate_thresholds in quality_matrix/matrix_report.json before changing presets.")
    else:
        steps.append("Run threshold matrix with 0.3,0.4,0.5,0.6 and pick the most human-correctable draft.")
    steps.append("If blockers remain sparse transcription or missing hihat/snare, use a cleaner drum stem or adjust ADTOF threshold preset.")
    return steps


def _external_rows(v1_eval: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in _list(v1_eval.get("fixtures")) if str(row.get("fixture", "")).startswith("external:")]


def _best_real_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return sorted(
        rows,
        key=lambda row: (
            bool(row.get("human_correctable")),
            int(_dict(row.get("quality_verdict")).get("usability_score") or 0),
            int(row.get("processed_event_count") or 0),
        ),
        reverse=True,
    )[0]


def _input_summary(path: Path) -> dict[str, Any]:
    return {"ref": f"external:{path.name}", "exists": path.exists(), "suffix": path.suffix.lower()}


def _write_outputs(output_dir: Path, report: dict[str, Any]) -> None:
    (output_dir / REPORT_FILENAME).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / HANDOFF_FILENAME).write_text(_render_handoff(report), encoding="utf-8")


def _render_handoff(report: dict[str, Any]) -> str:
    best = _dict(_dict(report.get("v1_eval")).get("best_real_audio"))
    lines = [
        "# GrooveScribe V1 Real Audio Pilot",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Input: `{_dict(report.get('input')).get('ref', 'external:unknown')}`",
        f"- Runtime: `{_dict(report.get('runtime')).get('status')}`",
        f"- Human-correctable: `{best.get('human_correctable', False)}`",
        f"- Primary blocker: `{best.get('primary_blocker', 'none')}`",
        "",
        "## Next Steps",
        "",
    ]
    for step in _list(report.get("next_steps")):
        lines.append(f"- {step}")
    lines.extend(
        [
            "",
            "## Policy",
            "",
            "- true-AI remains opt-in.",
            "- PDF renderer remains optional.",
            "- Real audio files and pilot artifacts stay outside git.",
        ]
    )
    rendered = "\n".join(lines) + "\n"
    return "[redacted]\n" if find_unsafe_tokens(rendered) else rendered


def _finalize(report: dict[str, Any]) -> dict[str, Any]:
    unsafe = find_unsafe_tokens(json.dumps(report, ensure_ascii=False))
    report["redaction"] = {"status": "passed" if not unsafe else "failed", "unsafe_token_count": len(unsafe)}
    if unsafe:
        return {
            "schema_version": "1.0",
            "status": "failed",
            "checked_at": datetime.now(UTC).isoformat(),
            "input": {"ref": "external:redacted", "exists": None, "suffix": None},
            "runtime": {"status": "redaction_failed"},
            "v1_eval": {"status": "redaction_failed"},
            "quality_matrix": {"status": "redaction_failed"},
            "manual_eval_seed": {"status": "blocked", "blocked_reason": "redaction_failed"},
            "review_packet": {"status": "requires_completed_backend_job"},
            "next_steps": ["Redaction failed while building real audio pilot report."],
            "redaction": {"status": "failed", "unsafe_token_count": len(unsafe)},
        }
    return report


def _parse_thresholds(value: str) -> tuple[str, ...]:
    parsed = tuple(item.strip() for item in value.split(",") if item.strip())
    return parsed or DEFAULT_THRESHOLD_MATRIX


def _inside_repo(path: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


def _failure(error: str) -> dict[str, str]:
    return {"schema_version": "1.0", "status": "failed", "error": error}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


if __name__ == "__main__":
    raise SystemExit(main())
