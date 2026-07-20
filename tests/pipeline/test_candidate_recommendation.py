from ai_pipeline.midi.candidate_recommendation import evaluate_candidate_recommendation


def _quality(
    *,
    flags: list[str] | None = None,
    tom_count: int = 2,
    dense_measures: int = 0,
    hihat_count: int = 32,
    measure_count: int = 1,
    verdict: str = "performance_ready",
) -> dict:
    return {
        "processed_drum_counts": {"kick": 16, "snare": 16, "closed_hat": hihat_count, "tom": tom_count},
        "quality_flags": flags or [],
        "notation_readability": {"dense_measure_count": dense_measures, "measure_count": measure_count},
        "performance_gate": {
            "verdict": verdict,
            "audio_alignment": {"onset_alignment_rate": 0.82},
        },
    }


def _validation(parseable: bool = True) -> dict:
    return {"musicxml": {"parseable": parseable}}


def test_candidate_recommendation_promotes_a_structurally_sound_practice_draft() -> None:
    result = evaluate_candidate_recommendation(
        status="completed",
        quality=_quality(),
        validation=_validation(),
    )

    assert result["recommendation"] == "recommended_for_practice"
    assert result["score"] >= 70
    assert result["rejected"] is False
    assert result["profile"] == "practice_coverage_v2"


def test_candidate_recommendation_rejects_missing_snare_or_blocking_flags() -> None:
    result = evaluate_candidate_recommendation(
        status="completed",
        quality={**_quality(flags=["sparse_transcription"]), "processed_drum_counts": {"kick": 4}},
        validation=_validation(),
    )

    assert result == {
        "schema_version": "1.0",
        "profile": "practice_coverage_v2",
        "score": 0,
        "recommendation": "reanalyze_recommended",
        "reasons": ["no_snare_detected", "sparse_transcription"],
        "rejected": True,
    }


def test_candidate_recommendation_keeps_low_confidence_draft_as_reference() -> None:
    result = evaluate_candidate_recommendation(
        status="completed",
        quality=_quality(tom_count=50, dense_measures=4),
        validation=_validation(),
    )

    assert result["recommendation"] == "reference_with_caveats"
    assert result["rejected"] is False


def test_candidate_recommendation_prefers_complete_hihat_coverage_over_low_confidence_gate() -> None:
    complete = evaluate_candidate_recommendation(
        status="completed",
        quality=_quality(hihat_count=124, measure_count=19, verdict="not_ready"),
        validation=_validation(),
    )
    sparse = evaluate_candidate_recommendation(
        status="completed",
        quality=_quality(hihat_count=69, measure_count=19, verdict="playable_but_low_confidence"),
        validation=_validation(),
    )

    assert complete["score"] > sparse["score"]
    assert "hi-hat 節奏覆蓋偏少" in sparse["reasons"]
