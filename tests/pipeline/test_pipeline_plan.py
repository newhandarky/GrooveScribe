from pathlib import Path

from ai_pipeline.runner import build_pipeline_plan


def test_pipeline_plan_contains_mvp_stages() -> None:
    plan = build_pipeline_plan(Path("sample.wav"), Path("out"))
    assert [stage.name for stage in plan.stages] == [
        "audio_preprocessing",
        "source_separation",
        "drum_transcription",
        "midi_post_processing",
        "notation_generation",
    ]


def test_pipeline_plan_keeps_model_adapters_explicit() -> None:
    plan = build_pipeline_plan(None, Path("out"))
    adapters = [stage.adapter for stage in plan.stages]
    assert "demucs" in adapters
    assert "adtof-pytorch" in adapters
