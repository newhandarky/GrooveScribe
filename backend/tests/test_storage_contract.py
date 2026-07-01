from app.storage.keys import build_job_artifact_key, sanitize_filename, sanitize_storage_key
from app.storage.types import ArtifactRef, ArtifactType, CONTENT_TYPE_BY_ARTIFACT_TYPE


def test_build_job_artifact_key_matches_storage_contract() -> None:
    assert build_job_artifact_key("job-1", ArtifactType.NORMALIZED_AUDIO) == "jobs/job-1/audio/normalized.wav"
    assert build_job_artifact_key("job-1", ArtifactType.DRUMS_STEM) == "jobs/job-1/stems/drums.wav"
    assert build_job_artifact_key("job-1", ArtifactType.RAW_MIDI) == "jobs/job-1/midi/raw_drum.mid"
    assert build_job_artifact_key("job-1", ArtifactType.PROCESSED_MIDI) == "jobs/job-1/midi/processed_drum.mid"
    assert build_job_artifact_key("job-1", ArtifactType.DRUM_EVENTS) == "jobs/job-1/midi/drum_events.json"
    assert build_job_artifact_key("job-1", ArtifactType.MUSICXML) == "jobs/job-1/notation/score.musicxml"
    assert build_job_artifact_key("job-1", ArtifactType.PDF) == "jobs/job-1/exports/score.pdf"
    assert build_job_artifact_key("job-1", ArtifactType.PIPELINE_LOG) == "jobs/job-1/logs/pipeline.json"


def test_original_audio_key_sanitizes_filename() -> None:
    key = build_job_artifact_key("job-1", ArtifactType.ORIGINAL_AUDIO, "My Song (draft).wav")
    assert key == "jobs/job-1/original/My_Song_draft.wav"


def test_storage_key_rejects_path_traversal() -> None:
    for key in ("../secret.wav", "jobs/../secret.wav", "/tmp/file.wav", "jobs" + chr(92) + "secret.wav"):
        try:
            sanitize_storage_key(key)
        except Exception as exc:
            assert getattr(exc, "code") == "PATH_TRAVERSAL_REJECTED"
        else:
            raise AssertionError(f"expected PATH_TRAVERSAL_REJECTED for {key}")


def test_artifact_ref_and_content_type_mapping() -> None:
    ref = ArtifactRef(
        storage_key="jobs/job-1/midi/processed_drum.mid",
        content_type=CONTENT_TYPE_BY_ARTIFACT_TYPE[ArtifactType.PROCESSED_MIDI],
        file_size_bytes=100,
        artifact_type=ArtifactType.PROCESSED_MIDI,
    )
    assert ref.content_type == "audio/midi"
    assert ref.file_size_bytes == 100


def test_sanitize_filename_rejects_empty_result() -> None:
    try:
        sanitize_filename(" ../ ")
    except Exception as exc:
        assert getattr(exc, "code") == "PATH_TRAVERSAL_REJECTED"
    else:
        raise AssertionError("expected PATH_TRAVERSAL_REJECTED")
