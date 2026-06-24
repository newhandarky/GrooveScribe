from pathlib import Path

from ai_pipeline.contracts import PipelinePlan, PipelineStage

PIPELINE_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage(
        name="audio_preprocessing",
        input_artifact="original_audio",
        output_artifact="normalized.wav",
        adapter="ffmpeg",
    ),
    PipelineStage(
        name="source_separation",
        input_artifact="normalized.wav",
        output_artifact="drums.wav",
        adapter="demucs",
    ),
    PipelineStage(
        name="drum_transcription",
        input_artifact="drums.wav",
        output_artifact="raw_drum.mid",
        adapter="adtof-pytorch",
    ),
    PipelineStage(
        name="midi_post_processing",
        input_artifact="raw_drum.mid",
        output_artifact="processed_drum.mid",
        adapter="groovescribe-midi-postprocessor",
    ),
    PipelineStage(
        name="notation_generation",
        input_artifact="processed_drum.mid",
        output_artifact="drum_score.musicxml + drum_score.pdf",
        adapter="music21",
    ),
)


def build_pipeline_plan(input_path: Path | None, output_dir: Path) -> PipelinePlan:
    return PipelinePlan(
        input_path=input_path,
        output_dir=output_dir,
        stages=PIPELINE_STAGES,
    )
