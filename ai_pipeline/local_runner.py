from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from ai_pipeline.midi import MidiPostProcessor
from ai_pipeline.midi.candidate_recommendation import evaluate_candidate_recommendation
from ai_pipeline.midi.quality import evaluate_drum_draft_quality, quality_flag_subset
from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import MidiPostProcessConfig, ProcessedDrumEvent
from ai_pipeline.notation import (
    MusicXmlGenerator,
    MuseScoreVisualQaRenderer,
    NotationConfig,
    validate_score_artifacts,
)
from ai_pipeline.notation.performance_gate import evaluate_performance_score
from ai_pipeline.preprocessing import FfmpegAudioNormalizer
from ai_pipeline.source_separation import DemucsSourceSeparator
from ai_pipeline.transcription import AdtofDrumTranscriber
from ai_pipeline.transcription.adtof import class_thresholds_for_preset
from ai_pipeline.transcription.benchmark_backends import SpectralOnsetDrumBackend


@dataclass(frozen=True)
class LocalPipelineConfig:
    mock_ai: bool = False
    export_pdf: bool = False
    require_pdf: bool = False
    visual_qa: bool = False
    title: str = "GrooveScribe Drum Draft"
    demucs_model_name: str = "htdemucs"
    demucs_device: str = "auto"
    demucs_timeout_seconds: int = 1_800
    adtof_command_template: str | None = None
    adtof_checkpoint_path: Path | None = None
    adtof_device: str = "cpu"
    transcription_backend: str = "adtof"
    adtof_threshold: float = 0.5
    adtof_class_thresholds: dict[str, float] | None = None
    adtof_threshold_preset: str | None = None
    adtof_timeout_seconds: int = 1_800
    tom_filter_preset: str | None = None
    tempo_bpm: float | None = None
    pdf_renderer: str | None = None
    performance_gate_calibration: dict | None = None
    candidate_thresholds: tuple[float, ...] = ()
    # Candidate families are deliberately explicit.  A scalar candidate must not
    # silently inherit a class preset, while a preset candidate records the
    # preset that actually produced its artifacts.
    candidate_threshold_presets: tuple[str, ...] = ()


@dataclass
class StageLog:
    name: str
    status: str
    started_at: str
    ended_at: str | None = None
    runtime_seconds: float | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    report: dict = field(default_factory=dict)
    error: dict | None = None


@dataclass
class LocalPipelineResult:
    status: str
    output_dir: Path
    log_path: Path
    artifacts: dict[str, Path]
    failed_stage: str | None = None


class LocalPipelineRunner:
    def __init__(self, config: LocalPipelineConfig | None = None) -> None:
        self.config = config or LocalPipelineConfig()

    def run(self, input_path: Path, output_dir: Path) -> LocalPipelineResult:
        if not input_path.exists():
            raise FileNotFoundError(f"input file does not exist: {input_path}")
        if (self.config.candidate_thresholds or self.config.candidate_threshold_presets) and self.config.transcription_backend != "adtof":
            raise ValueError("candidate_strategies_require_adtof_backend")
        unsupported_candidate_presets = set(self.config.candidate_threshold_presets) - {"separated_v1"}
        if unsupported_candidate_presets:
            raise ValueError("unsupported_candidate_threshold_preset")

        output_dir.mkdir(parents=True, exist_ok=True)
        if (self.config.candidate_thresholds or self.config.candidate_threshold_presets) and not self.config.mock_ai:
            return self._run_candidate_analysis(input_path, output_dir)
        artifacts: dict[str, Path] = {"original_audio": input_path}
        stage_logs: list[StageLog] = []
        log_path = output_dir / "logs" / "pipeline.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        for stage_name, stage_fn in (
            ("audio_preprocessing", self._run_audio_preprocessing),
            ("source_separation", self._run_source_separation),
            ("drum_transcription", self._run_drum_transcription),
            ("midi_post_processing", self._run_midi_post_processing),
            ("notation_generation", self._run_notation_generation),
        ):
            stage_log = StageLog(
                name=stage_name,
                status="running",
                started_at=_now_iso(),
            )
            started = time.monotonic()
            try:
                stage_artifacts, report = stage_fn(artifacts, output_dir)
                artifacts.update(stage_artifacts)
                stage_log.status = "completed"
                stage_log.artifacts = {name: str(path) for name, path in stage_artifacts.items()}
                stage_log.report = report
            except Exception as exc:
                stage_log.status = "failed"
                stage_log.error = _serialize_error(exc)
                stage_log.ended_at = _now_iso()
                stage_log.runtime_seconds = round(time.monotonic() - started, 4)
                stage_logs.append(stage_log)
                self._write_log(log_path, input_path, output_dir, "failed", stage_logs, artifacts)
                return LocalPipelineResult(
                    status="failed",
                    output_dir=output_dir,
                    log_path=log_path,
                    artifacts=artifacts,
                    failed_stage=stage_name,
                )

            stage_log.ended_at = _now_iso()
            stage_log.runtime_seconds = round(time.monotonic() - started, 4)
            stage_logs.append(stage_log)
            self._write_log(log_path, input_path, output_dir, "running", stage_logs, artifacts)

        self._write_log(log_path, input_path, output_dir, "completed", stage_logs, artifacts)
        return LocalPipelineResult(
            status="completed",
            output_dir=output_dir,
            log_path=log_path,
            artifacts=artifacts,
        )

    def _run_audio_preprocessing(
        self,
        artifacts: dict[str, Path],
        output_dir: Path,
    ) -> tuple[dict[str, Path], dict]:
        result = FfmpegAudioNormalizer().normalize(
            input_path=artifacts["original_audio"],
            output_dir=output_dir / "audio",
        )
        return {
            "normalized_audio": result.normalized_path,
        }, {
            "duration_seconds": result.metadata.duration_seconds,
            "sample_rate": result.metadata.sample_rate,
            "channels": result.metadata.channels,
            "format": result.metadata.format,
            "ffmpeg_version": result.metadata.ffmpeg_version,
        }

    def _run_source_separation(
        self,
        artifacts: dict[str, Path],
        output_dir: Path,
    ) -> tuple[dict[str, Path], dict]:
        if self.config.mock_ai:
            drums_path = output_dir / "stems" / "drums.wav"
            drums_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(artifacts["normalized_audio"], drums_path)
            return {"drums_stem": drums_path}, {
                "separator": "mock",
                "accompaniment_available": False,
                "warnings": ["mock_ai_enabled"],
            }

        separator = DemucsSourceSeparator(
            model_name=self.config.demucs_model_name,
            device=self.config.demucs_device,
            timeout_seconds=self.config.demucs_timeout_seconds,
        )
        result = separator.separate(artifacts["normalized_audio"], output_dir / "stems")
        stage_artifacts = {"drums_stem": result.drums_path}
        if result.accompaniment_path is not None:
            stage_artifacts["accompaniment_stem"] = result.accompaniment_path
        return stage_artifacts, {
            "separator": result.report.separator,
            "model_name": result.report.model_name,
            "device": result.report.device,
            "runtime_seconds": result.report.runtime_seconds,
            "accompaniment_available": result.accompaniment_path is not None,
            "warnings": list(result.report.warnings),
        }

    def _run_drum_transcription(
        self,
        artifacts: dict[str, Path],
        output_dir: Path,
    ) -> tuple[dict[str, Path], dict]:
        raw_midi_path = output_dir / "midi" / "raw_drum.mid"
        if self.config.mock_ai:
            events = (
                ProcessedDrumEvent(tick=0, note=36, drum="kick", velocity=105),
                ProcessedDrumEvent(tick=240, note=42, drum="closed_hat", velocity=78),
                ProcessedDrumEvent(tick=480, note=38, drum="snare", velocity=96),
                ProcessedDrumEvent(tick=720, note=42, drum="closed_hat", velocity=74),
                ProcessedDrumEvent(tick=960, note=36, drum="kick", velocity=102),
            )
            write_drum_midi(raw_midi_path, events, ticks_per_beat=480, tempo_bpm=120.0)
            return {"raw_midi": raw_midi_path}, {
                "transcriber": "mock",
                "event_count": len(events),
                "warnings": ["mock_ai_enabled"],
            }

        if self.config.transcription_backend == "spectral_onset_v1":
            result = SpectralOnsetDrumBackend().transcribe(
                artifacts["drums_stem"], raw_midi_path, tempo_bpm=self.config.tempo_bpm or 120.0
            )
            if result.get("status") != "completed":
                raise RuntimeError(str(result.get("reason_code") or "spectral_onset_unavailable"))
            return {"raw_midi": raw_midi_path}, {
                "transcriber": "spectral_onset_v1",
                "model_name": "spectral_onset_v1",
                "device": "cpu",
                "threshold": None,
                "threshold_preset": None,
                "class_thresholds": {},
                "event_count": result.get("event_count", 0),
                "warnings": [],
            }
        if self.config.transcription_backend != "adtof":
            raise ValueError("unsupported_transcription_backend")

        class_thresholds = self.config.adtof_class_thresholds or class_thresholds_for_preset(
            self.config.adtof_threshold_preset
        )
        if self.config.adtof_command_template:
            transcriber = AdtofDrumTranscriber.from_command_template_string(
                self.config.adtof_command_template,
                checkpoint_path=self.config.adtof_checkpoint_path,
                device=self.config.adtof_device,
                threshold=self.config.adtof_threshold,
                class_thresholds=class_thresholds,
                timeout_seconds=self.config.adtof_timeout_seconds,
            )
        else:
            transcriber = AdtofDrumTranscriber(
                checkpoint_path=self.config.adtof_checkpoint_path,
                device=self.config.adtof_device,
                threshold=self.config.adtof_threshold,
                class_thresholds=class_thresholds,
                timeout_seconds=self.config.adtof_timeout_seconds,
            )
        result = transcriber.transcribe(artifacts["drums_stem"], output_dir / "midi")
        return {"raw_midi": result.raw_midi_path}, {
            "transcriber": result.report.transcriber,
            "model_name": result.report.model_name,
            "device": result.report.device,
            "threshold": result.report.threshold,
            "threshold_preset": self.config.adtof_threshold_preset,
            "class_thresholds": result.report.class_thresholds,
            "event_count": result.metadata.event_count,
            "warnings": list(result.report.warnings),
        }

    def _run_midi_post_processing(
        self,
        artifacts: dict[str, Path],
        output_dir: Path,
    ) -> tuple[dict[str, Path], dict]:
        result = MidiPostProcessor(
            MidiPostProcessConfig(
                tom_filter_enabled=self.config.tom_filter_preset is not None,
                tom_filter_preset=self.config.tom_filter_preset,
            )
        ).process(artifacts["raw_midi"], output_dir / "midi")
        return {
            "processed_midi": result.processed_midi_path,
            "drum_events": result.drum_events_path,
        }, {
            "input_event_count": result.report.input_event_count,
            "output_event_count": result.report.output_event_count,
            "dropped_event_count": result.report.dropped_event_count,
            "estimated_bpm": result.report.estimated_bpm,
            "time_signature": result.report.time_signature,
            "warnings": list(result.report.warnings),
            "raw_note_histogram": {
                str(key): value for key, value in (result.report.raw_note_histogram or {}).items()
            },
            "processed_drum_counts": result.report.processed_drum_counts or {},
            "postprocess_filters": result.report.postprocess_filters or {},
            "quality_flags": quality_flag_subset(result.report.warnings),
        }

    def _run_notation_generation(
        self,
        artifacts: dict[str, Path],
        output_dir: Path,
    ) -> tuple[dict[str, Path], dict]:
        musicxml = MusicXmlGenerator(
            NotationConfig(
                title=self.config.title,
                tempo_bpm_override=self.config.tempo_bpm,
            )
        ).generate(
            artifacts["drum_events"],
            output_dir / "notation",
        )
        stage_artifacts = {
            "musicxml": musicxml.performance_musicxml_path,
            "performance_midi": musicxml.performance_midi_path,
            "chart_events": musicxml.chart_events_path,
        }
        pdf_path: Path | None = None
        visual_qa_report = {
            "status": "not_requested",
            "reason_code": "visual_qa_not_requested",
            "pdf_available": False,
            "first_page_png_available": False,
        }
        report = {
            "event_count": musicxml.event_count,
            "chart_event_count": musicxml.chart_event_count,
            "measure_count": musicxml.measure_count,
            "title": musicxml.title,
            "tempo_bpm": musicxml.tempo_bpm,
            "tempo_source": musicxml.tempo_source,
            "readability": musicxml.readability_summary,
            "chart": musicxml.chart_summary,
            "pdf": {"status": "skipped"},
            "visual_qa": visual_qa_report,
        }

        if self.config.export_pdf or self.config.require_pdf or self.config.visual_qa:
            visual_qa = MuseScoreVisualQaRenderer(renderer_binary=self.config.pdf_renderer).render(
                musicxml.performance_musicxml_path,
                output_dir / "exports",
            )
            visual_qa_report = visual_qa.report()
            report["visual_qa"] = visual_qa_report
            if visual_qa.pdf_path is not None:
                stage_artifacts["pdf"] = visual_qa.pdf_path
                pdf_path = visual_qa.pdf_path
            if visual_qa.first_page_png_path is not None:
                stage_artifacts["visual_preview"] = visual_qa.first_page_png_path
            report["pdf"] = {
                "status": "completed" if pdf_path is not None else "unavailable",
                "reason_code": visual_qa.reason_code,
            }

        report["validation"] = validate_score_artifacts(
            musicxml.performance_musicxml_path,
            pdf_path,
            visual_qa=visual_qa_report,
        )
        report["performance_gate"] = evaluate_performance_score(
            chart_events_path=musicxml.chart_events_path,
            performance_midi_path=musicxml.performance_midi_path,
            performance_musicxml_path=musicxml.performance_musicxml_path,
            drums_stem_path=artifacts.get("drums_stem"),
            gate_calibration=self.config.performance_gate_calibration,
        )
        return stage_artifacts, report

    def _write_log(
        self,
        log_path: Path,
        input_path: Path,
        output_dir: Path,
        status: str,
        stage_logs: list[StageLog],
        artifacts: dict[str, Path],
        candidate_analysis: dict | None = None,
    ) -> None:
        payload = {
            "schema_version": "1.0",
            "status": status,
            "input_path": str(input_path),
            "output_dir": str(output_dir),
            "mock_ai": self.config.mock_ai,
            "artifacts": {name: str(path) for name, path in artifacts.items()},
            "stages": [asdict(stage_log) for stage_log in stage_logs],
            "quality": _build_quality_summary(stage_logs),
            "validation": _build_validation_summary(stage_logs),
        }
        if candidate_analysis is not None:
            payload["candidate_analysis"] = candidate_analysis
        log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _run_candidate_analysis(self, input_path: Path, output_dir: Path) -> LocalPipelineResult:
        artifacts: dict[str, Path] = {"original_audio": input_path}
        shared_logs: list[StageLog] = []
        log_path = output_dir / "logs" / "pipeline.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        for stage_name, stage_fn in (
            ("audio_preprocessing", self._run_audio_preprocessing),
            ("source_separation", self._run_source_separation),
        ):
            started = time.monotonic()
            stage_log = StageLog(name=stage_name, status="running", started_at=_now_iso())
            try:
                stage_artifacts, report = stage_fn(artifacts, output_dir)
                artifacts.update(stage_artifacts)
                stage_log.status = "completed"
                stage_log.artifacts = {name: str(path) for name, path in stage_artifacts.items()}
                stage_log.report = report
            except Exception as exc:
                stage_log.status = "failed"
                stage_log.error = _serialize_error(exc)
                stage_log.ended_at = _now_iso()
                stage_log.runtime_seconds = round(time.monotonic() - started, 4)
                shared_logs.append(stage_log)
                self._write_log(log_path, input_path, output_dir, "failed", shared_logs, artifacts)
                return LocalPipelineResult("failed", output_dir, log_path, artifacts, stage_name)
            stage_log.ended_at = _now_iso()
            stage_log.runtime_seconds = round(time.monotonic() - started, 4)
            shared_logs.append(stage_log)

        candidates: list[dict] = []
        successful: list[tuple[dict, dict[str, Path], list[StageLog]]] = []
        for index, candidate_spec in enumerate(self._candidate_specs(), start=1):
            candidate_id = candidate_spec["candidate_id"]
            candidate_artifacts = dict(artifacts)
            candidate_logs: list[StageLog] = []
            candidate_dir = output_dir / "candidates" / candidate_id
            failed_stage = None
            # ADTOF accepts either its per-class threshold preset or a scalar threshold.
            # Each candidate declares exactly one strategy, so a scalar candidate
            # cannot be silently masked by a class-preset candidate.
            candidate_runner = LocalPipelineRunner(
                replace(
                    self.config,
                    adtof_threshold=candidate_spec["threshold"] if candidate_spec["threshold"] is not None else self.config.adtof_threshold,
                    adtof_class_thresholds=None,
                    adtof_threshold_preset=candidate_spec["adtof_threshold_preset"],
                    candidate_thresholds=(),
                    candidate_threshold_presets=(),
                )
            )
            for stage_name, stage_fn in (
                ("drum_transcription", candidate_runner._run_drum_transcription),
                ("midi_post_processing", candidate_runner._run_midi_post_processing),
                ("notation_generation", candidate_runner._run_notation_generation),
            ):
                started = time.monotonic()
                stage_log = StageLog(name=stage_name, status="running", started_at=_now_iso())
                try:
                    stage_artifacts, report = stage_fn(candidate_artifacts, candidate_dir)
                    candidate_artifacts.update(stage_artifacts)
                    stage_log.status = "completed"
                    stage_log.artifacts = {name: str(path) for name, path in stage_artifacts.items()}
                    stage_log.report = report
                except Exception as exc:
                    failed_stage = stage_name
                    stage_log.status = "failed"
                    stage_log.error = _serialize_error(exc)
                stage_log.ended_at = _now_iso()
                stage_log.runtime_seconds = round(time.monotonic() - started, 4)
                candidate_logs.append(stage_log)
                if failed_stage:
                    break
            quality = _build_quality_summary(candidate_logs) or {}
            validation = _build_validation_summary(candidate_logs) or {}
            recommendation = evaluate_candidate_recommendation(
                status="failed" if failed_stage else "completed",
                quality=quality,
                validation=validation,
            )
            candidate = {
                "candidate_id": candidate_id,
                "position": index,
                "status": "failed" if failed_stage else "completed",
                "config": {
                    "threshold": candidate_spec["threshold"],
                    "adtof_threshold_preset": candidate_spec["adtof_threshold_preset"],
                    "strategy": candidate_spec["strategy"],
                    "tom_filter_preset": self.config.tom_filter_preset,
                },
                "failed_stage": failed_stage,
                "failure_reason_code": _candidate_failure_reason_code(failed_stage),
                "artifacts": {name: str(path) for name, path in candidate_artifacts.items() if name not in {"original_audio", "normalized_audio", "drums_stem", "accompaniment_stem"}},
                "quality": quality,
                "validation": validation,
                "recommendation": recommendation,
            }
            candidates.append(candidate)
            if not failed_stage and validation.get("musicxml", {}).get("parseable"):
                successful.append((candidate, candidate_artifacts, candidate_logs))

        if not successful:
            analysis = {"schema_version": "1.0", "status": "failed", "recommended_candidate_id": None, "candidates": candidates}
            self._write_log(log_path, input_path, output_dir, "failed", shared_logs, artifacts, analysis)
            return LocalPipelineResult("failed", output_dir, log_path, artifacts, "candidate_analysis")
        eligible = [item for item in successful if not bool(item[0]["recommendation"].get("rejected"))]
        ranked = sorted(
            eligible,
            key=lambda item: (-int(item[0]["recommendation"].get("score") or 0), int(item[0]["position"])),
        )
        for rank, (candidate, _candidate_artifacts, _candidate_logs) in enumerate(ranked, start=1):
            candidate["rank"] = rank
        # A parseable but hard-rejected candidate remains available for diagnostic
        # review and legacy downloads. It must never be presented as a recommendation.
        selected, selected_artifacts, selected_logs = (
            ranked[0]
            if ranked
            else min(successful, key=lambda item: int(item[0]["position"]))
        )
        candidate_id = str(selected["candidate_id"])
        for candidate in candidates:
            candidate["selected"] = candidate["candidate_id"] == candidate_id
        shared_artifact_names = {"original_audio", "normalized_audio", "drums_stem", "accompaniment_stem"}
        final_artifacts = {
            **artifacts,
            **{name: path for name, path in selected_artifacts.items() if name not in shared_artifact_names},
        }
        final_logs = [*shared_logs, *selected_logs]
        analysis = {
            "schema_version": "1.1",
            "status": "completed",
            "strategy_profile": self._candidate_strategy_profile(),
            "recommended_candidate_id": candidate_id if ranked else None,
            "canonical_candidate_id": candidate_id,
            "candidates": candidates,
        }
        self._write_log(log_path, input_path, output_dir, "completed", final_logs, final_artifacts, analysis)
        return LocalPipelineResult("completed", output_dir, log_path, final_artifacts)

    def _candidate_specs(self) -> tuple[dict[str, object], ...]:
        scalar = tuple(
            {
                "candidate_id": f"threshold_{str(threshold).replace('.', '_')}",
                "threshold": threshold,
                "adtof_threshold_preset": None,
                "strategy": "scalar_threshold_v1",
            }
            for threshold in self.config.candidate_thresholds
        )
        presets = tuple(
            {
                "candidate_id": f"preset_{preset}",
                "threshold": None,
                "adtof_threshold_preset": preset,
                "strategy": "adtof_preset_v1",
            }
            for preset in self.config.candidate_threshold_presets
        )
        return scalar + presets

    def _candidate_strategy_profile(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "families": [
                *(["scalar_threshold_v1"] if self.config.candidate_thresholds else []),
                *(["adtof_preset_v1"] if self.config.candidate_threshold_presets else []),
            ],
        }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _serialize_error(exc: Exception) -> dict[str, str]:
    return {
        "type": exc.__class__.__name__,
        "code": getattr(exc, "code", exc.__class__.__name__),
        "message": str(exc),
    }


def _candidate_failure_reason_code(failed_stage: str | None) -> str | None:
    """Keep candidate failures actionable without forwarding runtime diagnostics."""

    return {
        "drum_transcription": "candidate_transcription_failed",
        "midi_post_processing": "candidate_postprocess_failed",
        "notation_generation": "candidate_notation_failed",
    }.get(failed_stage)


def _build_quality_summary(stage_logs: list[StageLog]) -> dict | None:
    midi_report = _stage_report(stage_logs, "midi_post_processing")
    if midi_report is None:
        return None
    notation_report = _stage_report(stage_logs, "notation_generation") or {}

    warnings = [str(warning) for warning in midi_report.get("warnings", []) if isinstance(warning, str)]
    validation = _build_validation_summary(stage_logs) or {}
    musicxml = validation.get("musicxml") if isinstance(validation.get("musicxml"), dict) else {}
    visual_qa = validation.get("visual_qa") if isinstance(validation.get("visual_qa"), dict) else {}
    processed_counts = _string_int_dict(midi_report.get("processed_drum_counts"))
    quality_flags = midi_report.get("quality_flags") or quality_flag_subset(warnings)
    verdict = evaluate_drum_draft_quality(
        processed_drum_counts=processed_counts,
        processed_event_count=midi_report.get("output_event_count"),
        quality_flags=quality_flags,
        musicxml_available=bool(musicxml.get("available")),
        musicxml_parseable=bool(musicxml.get("parseable")),
    )
    performance_gate = notation_report.get("performance_gate") if isinstance(notation_report.get("performance_gate"), dict) else {}
    return {
        "schema_version": "1.0",
        "raw_event_count": midi_report.get("input_event_count"),
        "processed_event_count": midi_report.get("output_event_count"),
        "raw_note_histogram": _string_int_dict(midi_report.get("raw_note_histogram")),
        "processed_drum_counts": processed_counts,
        "duration_seconds": _first_number(stage_logs, "audio_preprocessing", "duration_seconds"),
        "tempo_bpm": notation_report.get("tempo_bpm") or midi_report.get("estimated_bpm"),
        "tempo_source": notation_report.get("tempo_source") or "estimated",
        "estimated_measure_count": notation_report.get("measure_count"),
        "musicxml_parseable": bool(musicxml.get("parseable")),
        "visual_qa_status": visual_qa.get("status") or "not_reported",
        "visual_qa_reason_code": visual_qa.get("reason_code"),
        "notation_readability": notation_report.get("readability") or {},
        "notation_chart": notation_report.get("chart") or {},
        "quality_flags": quality_flags,
        "warnings": sorted(set(warnings)),
        "postprocess_filters": midi_report.get("postprocess_filters") or {},
        "quality_verdict": verdict,
        "performance_gate": performance_gate,
    }


def _build_validation_summary(stage_logs: list[StageLog]) -> dict | None:
    notation_report = _stage_report(stage_logs, "notation_generation")
    if notation_report is None:
        return None
    validation = notation_report.get("validation")
    return validation if isinstance(validation, dict) else None


def _stage_report(stage_logs: list[StageLog], name: str) -> dict | None:
    for stage_log in stage_logs:
        if stage_log.name == name and stage_log.status == "completed":
            return stage_log.report
    return None


def _first_number(stage_logs: list[StageLog], stage_name: str, key: str) -> float | None:
    report = _stage_report(stage_logs, stage_name)
    if report is None:
        return None
    value = report.get(key)
    return value if isinstance(value, int | float) else None


def _string_int_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        if isinstance(item, int):
            result[str(key)] = item
    return dict(sorted(result.items()))
