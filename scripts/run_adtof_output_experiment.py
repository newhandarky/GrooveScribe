from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from ai_pipeline.midi.mapping import map_to_general_midi_drum
from scripts.redaction import find_unsafe_tokens
from ai_pipeline.transcription.adtof import (
    ADTOF_CLASS_THRESHOLD_NOTES,
    ADTOF_CLASS_THRESHOLD_ORDER,
    class_thresholds_csv,
    class_thresholds_for_preset,
    parse_class_thresholds,
)
from scripts.run_true_ai_quality_matrix import QualityMatrixConfig, run_quality_matrix

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = _REPO_ROOT / "tests" / "pipeline" / "fixtures" / "audio" / "synthetic_separated_kick_snare_hat_pattern.wav"
DEFAULT_THRESHOLDS = ("0.1", "0.15", "0.2", "0.25", "0.3")
REPORT_NAME = "adtof_output_experiment_report.json"
ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class AdtofOutputExperimentConfig:
    fixture: Path
    output_dir: Path
    thresholds: tuple[str, ...]
    ai_python: str
    demucs_device: str
    adtof_command_template: str | None
    adtof_checkpoint: str | None
    adtof_device: str
    timeout_seconds: int
    per_class_configs: tuple[str, ...] = ()
    threshold_preset: str | None = None
    tom_filter_preset: str | None = None
    per_class_scalar_threshold: str = "0.06"
    export_pdf: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a focused ADTOF raw-output experiment for one fixture.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/groovescribe-adtof-output-experiment"))
    parser.add_argument("--thresholds", default=",".join(DEFAULT_THRESHOLDS))
    parser.add_argument("--ai-python", default=os.environ.get("AI_PYTHON", sys.executable))
    parser.add_argument("--demucs-device", default=os.environ.get("GROOVESCRIBE_DEMUCS_DEVICE", "cpu"))
    parser.add_argument("--adtof-command-template", default=os.environ.get("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"))
    parser.add_argument("--adtof-checkpoint", default=os.environ.get("GROOVESCRIBE_ADTOF_CHECKPOINT"))
    parser.add_argument("--adtof-device", default=os.environ.get("GROOVESCRIBE_ADTOF_DEVICE", "cpu"))
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("PIPELINE_TRUE_AI_TIMEOUT_SECONDS", "3600")))
    parser.add_argument(
        "--per-class-config",
        action="append",
        default=[],
        help=(
            "Optional named per-class config, e.g. "
            "A:kick=0.06,snare=0.04,tom=0.12,closed_hat=0.06,cymbal=0.08"
        ),
    )
    parser.add_argument("--threshold-preset", default=None, help="Optional opt-in threshold preset, e.g. separated_v1")
    parser.add_argument("--tom-filter-preset", default=os.environ.get("GROOVESCRIBE_TOM_FILTER_PRESET"))
    parser.add_argument("--per-class-scalar-threshold", default="0.06")
    parser.add_argument("--export-pdf", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_adtof_output_experiment(
        AdtofOutputExperimentConfig(
            fixture=args.fixture,
            output_dir=args.output_dir,
            thresholds=_parse_thresholds(args.thresholds),
            ai_python=args.ai_python,
            demucs_device=args.demucs_device,
            adtof_command_template=args.adtof_command_template,
            adtof_checkpoint=args.adtof_checkpoint,
            adtof_device=args.adtof_device,
            timeout_seconds=args.timeout_seconds,
            per_class_configs=tuple(args.per_class_config or ()),
            threshold_preset=args.threshold_preset,
            tom_filter_preset=args.tom_filter_preset,
            per_class_scalar_threshold=args.per_class_scalar_threshold,
            export_pdf=args.export_pdf,
        )
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "output_dir_name": report["output_dir_name"],
                "experiment_report_name": REPORT_NAME,
            },
            indent=2,
        )
    )
    return 0 if report["status"] in {"completed", "completed_with_failures", "blocked", "skipped"} else 1


def run_adtof_output_experiment(
    config: AdtofOutputExperimentConfig,
    *,
    process_runner: ProcessRunner = subprocess.run,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    checked = checked_at or datetime.now(UTC)
    output_dir = config.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    matrix = _run_matrix(
        config,
        thresholds=config.thresholds,
        adtof_class_thresholds=None,
        process_runner=process_runner,
        checked_at=checked,
        output_dir=output_dir,
    )
    per_class_configs = list(config.per_class_configs)
    if config.threshold_preset:
        per_class_configs.append(config.threshold_preset)
    per_class_matrices = [
        (
            label,
            thresholds,
            _run_matrix(
                config,
                thresholds=(config.per_class_scalar_threshold,),
                adtof_class_thresholds=thresholds_text,
                process_runner=process_runner,
                checked_at=checked,
                output_dir=output_dir,
            ),
        )
        for label, thresholds, thresholds_text in (_parse_per_class_config(item) for item in per_class_configs)
    ]
    combined_statuses = [str(matrix.get("status"))] + [str(item[2].get("status")) for item in per_class_matrices]
    status = _combined_status(combined_statuses)
    fixture = _first_fixture(matrix)
    runs = [_experiment_run(run, threshold_mode="scalar", class_thresholds=None) for run in fixture.get("runs", [])]
    for label, thresholds, per_class_matrix in per_class_matrices:
        per_class_fixture = _first_fixture(per_class_matrix)
        for run in per_class_fixture.get("runs", []):
            enriched = _experiment_run(run, threshold_mode="per_class", class_thresholds=thresholds)
            enriched["threshold"] = label
            enriched["scalar_threshold"] = config.per_class_scalar_threshold
            runs.append(enriched)
    candidate_thresholds = [
        {
            "threshold": run.get("threshold"),
            "threshold_mode": run.get("threshold_mode"),
            "scalar_threshold": run.get("scalar_threshold"),
            "class_thresholds": run.get("class_thresholds"),
            "processed_event_count": run.get("processed_event_count"),
            "processed_drum_counts": run.get("processed_drum_counts"),
            "quality_flags": run.get("quality_flags"),
            "usability_score": run.get("usability_score"),
        }
        for run in runs
        if _dict(run.get("candidate_gate")).get("status") == "passed"
    ]
    report = {
        "schema_version": "1.0",
        "status": status,
        "checked_at": checked.isoformat(),
        "fixture": _display_fixture(config.fixture),
        "output_dir_name": output_dir.name,
        "thresholds": list(config.thresholds),
        "per_class_threshold_supported": True,
        "threshold_preset": config.threshold_preset,
        "per_class_threshold_order": list(ADTOF_CLASS_THRESHOLD_ORDER),
        "per_class_threshold_notes": {name: ADTOF_CLASS_THRESHOLD_NOTES[name] for name in ADTOF_CLASS_THRESHOLD_ORDER},
        "per_class_threshold_note": (
            "Installed adtof_pytorch supports --thresholds in LABELS_5 order: "
            "kick(35), snare(38), tom(47), closed_hat(42), cymbal(49)."
        ),
        "matrix_status": matrix.get("status"),
        "fixture_status": fixture.get("status"),
        "candidate_thresholds": candidate_thresholds,
        "runs": runs,
        "conclusion": _conclusion(runs),
    }
    unsafe = find_unsafe_tokens(json.dumps(report, ensure_ascii=False))
    report["redaction"] = {"status": "passed" if not unsafe else "failed", "unsafe_token_count": len(unsafe)}
    if unsafe:
        report["status"] = "failed"
    (output_dir / REPORT_NAME).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _run_matrix(
    config: AdtofOutputExperimentConfig,
    *,
    thresholds: tuple[str, ...],
    adtof_class_thresholds: str | None,
    process_runner: ProcessRunner,
    checked_at: datetime,
    output_dir: Path,
) -> dict[str, Any]:
    return run_quality_matrix(
        QualityMatrixConfig(
            fixtures=(config.fixture,),
            output_dir=output_dir,
            thresholds=thresholds,
            ai_python=config.ai_python,
            demucs_device=config.demucs_device,
            adtof_command_template=config.adtof_command_template,
            adtof_checkpoint=config.adtof_checkpoint,
            adtof_device=config.adtof_device,
            timeout_seconds=config.timeout_seconds,
            adtof_class_thresholds=adtof_class_thresholds,
            tom_filter_preset=config.tom_filter_preset,
            export_pdf=config.export_pdf,
        ),
        process_runner=process_runner,
        checked_at=checked_at,
    )


def _experiment_run(
    run: dict[str, Any],
    *,
    threshold_mode: str,
    class_thresholds: dict[str, float] | None,
) -> dict[str, Any]:
    raw_note_histogram = _dict(run.get("raw_note_histogram"))
    processed_drum_counts = _dict(run.get("processed_drum_counts"))
    hihat_count = _hihat_count(processed_drum_counts)
    candidate_gate = _dict(run.get("minimum_gate"))
    quality_flags = _list(run.get("quality_flags"))
    return {
        "threshold": run.get("threshold"),
        "threshold_mode": threshold_mode,
        "scalar_threshold": run.get("threshold"),
        "class_thresholds": class_thresholds,
        "status": run.get("status"),
        "raw_event_count": run.get("raw_event_count"),
        "processed_event_count": run.get("processed_event_count"),
        "raw_note_histogram": raw_note_histogram,
        "raw_mapping_verification": mapping_verification(raw_note_histogram),
        "processed_drum_counts": processed_drum_counts,
        "postprocess_filters": _dict(run.get("postprocess_filters")),
        "kick_count": int(processed_drum_counts.get("kick", 0)),
        "snare_count": int(processed_drum_counts.get("snare", 0)),
        "hihat_count": hihat_count,
        "tom_count": int(processed_drum_counts.get("tom", 0)),
        "quality_flags": quality_flags,
        "musicxml": _dict(run.get("musicxml")),
        "candidate_gate": candidate_gate,
        "usability_score": usability_score(
            status=str(run.get("status")),
            processed_event_count=_int_or_none(run.get("processed_event_count")),
            processed_drum_counts=processed_drum_counts,
            quality_flags=quality_flags,
            musicxml=_dict(run.get("musicxml")),
            candidate_gate=candidate_gate,
        ),
    }


def mapping_verification(raw_note_histogram: dict[str, Any]) -> dict[str, Any]:
    notes = []
    raw_snare_present = False
    raw_hihat_present = False
    raw_tom_count = 0
    for note_text, count in sorted(raw_note_histogram.items(), key=lambda item: int(item[0])):
        note = int(note_text)
        event_count = int(count)
        mapping = map_to_general_midi_drum(note)
        drum = mapping.drum if mapping else None
        if drum == "snare":
            raw_snare_present = True
        if drum in {"closed_hat", "pedal_hat", "open_hat"}:
            raw_hihat_present = True
        if drum == "tom":
            raw_tom_count += event_count
        notes.append(
            {
                "raw_note": note,
                "count": event_count,
                "mapped_note": mapping.note if mapping else None,
                "mapped_drum": drum,
                "mapping_source": "general_midi",
            }
        )
    return {
        "mapping_source": "general_midi",
        "no_evidence_remap_applied": True,
        "raw_snare_present": raw_snare_present,
        "raw_hihat_present": raw_hihat_present,
        "raw_tom_count": raw_tom_count,
        "notes": notes,
    }


def _conclusion(runs: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        run
        for run in runs
        if run.get("status") == "completed" and _dict(run.get("candidate_gate")).get("status") == "passed"
    ]
    best = _best_run(runs)
    return {
        "candidate_found": bool(candidates),
        "best_threshold": best.get("threshold") if best else None,
        "best_usability_score": best.get("usability_score") if best else None,
        "snare_seen_in_raw": any(_dict(run.get("raw_mapping_verification")).get("raw_snare_present") for run in runs),
        "snare_seen_in_processed": any(_dict(run.get("processed_drum_counts")).get("snare", 0) for run in runs),
        "likely_next_step": "use_alternative_transcription_backend_spike" if not candidates else "manual_evaluate_candidate",
    }


def _best_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    completed = [run for run in runs if run.get("status") == "completed"]
    if not completed:
        return runs[0] if runs else None

    def score(run: dict[str, Any]) -> tuple[int, int, int, int, int]:
        counts = _dict(run.get("processed_drum_counts"))
        flags = set(str(item) for item in _list(run.get("quality_flags")))
        core = int(bool(counts.get("kick"))) + int(bool(counts.get("snare"))) + int(
            any(counts.get(drum) for drum in ("closed_hat", "pedal_hat", "open_hat"))
        )
        blockers = sum(1 for flag in ("mostly_tom_output", "no_snare_detected", "no_usable_groove") if flag in flags)
        return (int(run.get("usability_score") or 0), core, -blockers, int(run.get("processed_event_count") or 0), -len(flags))

    return max(completed, key=score)


def usability_score(
    *,
    status: str,
    processed_event_count: int | None,
    processed_drum_counts: dict[str, Any],
    quality_flags: list[Any],
    musicxml: dict[str, Any],
    candidate_gate: dict[str, Any],
) -> int:
    if status != "completed" or not musicxml.get("available") or not musicxml.get("parseable"):
        return 1
    flags = {str(flag) for flag in quality_flags}
    if candidate_gate.get("status") != "passed":
        return 1 if {"no_usable_groove", "too_few_events"} & flags else 2

    kick_count = int(processed_drum_counts.get("kick", 0))
    snare_count = int(processed_drum_counts.get("snare", 0))
    hihat_count = _hihat_count(processed_drum_counts)
    tom_count = int(processed_drum_counts.get("tom", 0))
    event_count = processed_event_count if processed_event_count is not None else sum(
        int(count) for count in processed_drum_counts.values()
    )
    if not (kick_count and snare_count and hihat_count):
        return 2
    tom_ratio = tom_count / event_count if event_count else 1.0
    if snare_count >= 3 and hihat_count >= 4 and tom_ratio <= 0.2:
        return 5
    if snare_count >= 2 and hihat_count >= 2 and tom_ratio <= 0.3:
        return 4
    return 3


def _first_fixture(matrix: dict[str, Any]) -> dict[str, Any]:
    fixtures = _list(matrix.get("fixtures"))
    return fixtures[0] if fixtures and isinstance(fixtures[0], dict) else {}


def _display_fixture(path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return str(resolved.relative_to(_REPO_ROOT))
    except ValueError:
        return f"external:{resolved.name}"


def _parse_thresholds(value: str) -> tuple[str, ...]:
    thresholds = tuple(item.strip() for item in value.split(",") if item.strip())
    return thresholds or DEFAULT_THRESHOLDS


def _parse_per_class_config(value: str) -> tuple[str, dict[str, float], str]:
    if ":" in value:
        label, raw_thresholds = value.split(":", 1)
        label = label.strip() or "per_class"
    elif "=" not in value:
        preset_thresholds = class_thresholds_for_preset(value)
        if preset_thresholds is not None:
            return value, preset_thresholds, class_thresholds_csv(preset_thresholds)
        label = "per_class"
        raw_thresholds = value
    else:
        label = "per_class"
        raw_thresholds = value
    thresholds = parse_class_thresholds(raw_thresholds)
    if thresholds is None:
        raise ValueError("per-class config is empty")
    return label, thresholds, raw_thresholds


def _combined_status(statuses: list[str]) -> str:
    if statuses and all(status == "completed" for status in statuses):
        return "completed"
    if any(status in {"completed", "completed_with_failures"} for status in statuses):
        return "completed_with_failures"
    if any(status == "blocked" for status in statuses):
        return "blocked"
    if any(status == "failed" for status in statuses):
        return "failed"
    return statuses[0] if statuses else "unknown"


def _hihat_count(counts: dict[str, Any]) -> int:
    return sum(int(counts.get(drum, 0)) for drum in ("closed_hat", "pedal_hat", "open_hat"))


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


if __name__ == "__main__":
    raise SystemExit(main())
