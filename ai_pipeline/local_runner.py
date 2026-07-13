from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ai_pipeline.midi import MidiPostProcessor
from ai_pipeline.midi.quality import evaluate_drum_draft_quality, quality_flag_subset
from ai_pipeline.midi.simple_midi import write_drum_midi
from ai_pipeline.midi.types import MidiPostProcessConfig, ProcessedDrumEvent
from ai_pipeline.notation import (
    MusicXmlGenerator,
    MuseScoreVisualQaRenderer,
    NotationConfig,
    validate_score_artifacts,
)
from ai_pipeline.preprocessing import FfmpegAudioNormalizer
from ai_pipeline.source_separation import DemucsSourceSeparator
from ai_pipeline.transcription import AdtofDrumTranscriber
from ai_pipeline.transcription.adtof import class_thresholds_for_preset


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
    adtof_threshold: float = 0.5
    adtof_class_thresholds: dict[str, float] | None = None
    adtof_threshold_preset: str | None = None
    adtof_timeout_seconds: int = 1_800
    tom_filter_preset: str | None = None
    tempo_bpm: float | None = None
    pdf_renderer: str | None = None


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

        output_dir.mkdir(parents=True, exist_ok=True)
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
            return {"drums_stem": drums_path}, {"separator": "mock", "warnings": ["mock_ai_enabled"]}

        separator = DemucsSourceSeparator(
            model_name=self.config.demucs_model_name,
            device=self.config.demucs_device,
            timeout_seconds=self.config.demucs_timeout_seconds,
        )
        result = separator.separate(artifacts["normalized_audio"], output_dir / "stems")
        return {"drums_stem": result.drums_path}, {
            "separator": result.report.separator,
            "model_name": result.report.model_name,
            "device": result.report.device,
            "runtime_seconds": result.report.runtime_seconds,
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
        stage_artifacts = {"musicxml": musicxml.musicxml_path, "chart_events": musicxml.chart_events_path}
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
                musicxml.musicxml_path,
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
            musicxml.musicxml_path,
            pdf_path,
            visual_qa=visual_qa_report,
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
        log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _serialize_error(exc: Exception) -> dict[str, str]:
    return {
        "type": exc.__class__.__name__,
        "code": getattr(exc, "code", exc.__class__.__name__),
        "message": str(exc),
    }


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
