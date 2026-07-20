from __future__ import annotations

from typing import Any

_BLOCKING_FLAGS = {
    "too_few_events",
    "sparse_transcription",
    "mostly_tom_output",
    "no_snare_detected",
}
_PROFILE = "practice_coverage_v2"


def evaluate_candidate_recommendation(
    *,
    status: str,
    quality: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any]:
    """Rank a candidate conservatively without treating a user upload as truth."""

    counts = _dict(quality.get("processed_drum_counts"))
    flags = {str(value) for value in _list(quality.get("quality_flags"))}
    gate = _dict(quality.get("performance_gate"))
    musicxml = _dict(validation.get("musicxml"))
    hard_reasons: list[str] = []
    if status != "completed":
        hard_reasons.append("candidate_not_completed")
    if not musicxml.get("parseable"):
        hard_reasons.append("musicxml_unparseable")
    if not _positive(counts.get("kick")):
        hard_reasons.append("kick_missing")
    if not _positive(counts.get("snare")):
        hard_reasons.append("no_snare_detected")
    hard_reasons.extend(sorted(flags & _BLOCKING_FLAGS))
    if hard_reasons:
        return _result(0, "reanalyze_recommended", hard_reasons, rejected=True)

    score = 30
    reasons = ["已產生可讀取的鼓譜"]
    alignment = _number(_dict(gate.get("audio_alignment")).get("onset_alignment_rate"))
    if alignment is not None:
        score += round(min(1.0, alignment) * 25)
        reasons.append("鼓點與分離鼓聲的對齊較佳" if alignment >= 0.7 else "鼓點對齊仍需保留參考")
    hihat = sum(_positive(counts.get(name)) for name in ("closed_hat", "open_hat", "pedal_hat"))
    notation = _dict(quality.get("notation_readability"))
    measure_count = max(1, _positive(notation.get("measure_count")))
    minimum_hihat_events = max(2, measure_count * 4)
    if hihat >= minimum_hihat_events:
        score += 12
    elif hihat:
        score -= 10
        reasons.insert(0, "hi-hat 節奏覆蓋偏少")
    else:
        score -= 12
        reasons.append("hi-hat 細節可能不完整")
    total = sum(_positive(value) for value in counts.values())
    tom = _positive(counts.get("tom"))
    if total and tom / total <= 0.35:
        score += 10
    else:
        score -= 10
        reasons.append("tom 事件比例偏高")
    verdict = str(gate.get("verdict") or "")
    if verdict == "performance_ready":
        score += 15
    elif verdict == "playable_but_low_confidence":
        score += 4
    elif verdict:
        score -= 4
    if _positive(notation.get("dense_measure_count")) == 0:
        score += 8
    score -= min(15, len(flags) * 4)
    score = max(0, min(100, score))
    recommendation = "recommended_for_practice" if score >= 70 else "reference_with_caveats" if score >= 42 else "reanalyze_recommended"
    if recommendation == "recommended_for_practice":
        reasons = ["節奏與譜面結構相對穩定", *reasons]
    elif recommendation == "reference_with_caveats":
        reasons = ["可用於跟練，但部分細節可能不準", *reasons]
    else:
        reasons = ["自動檢查未達適合練習的門檻", *reasons]
    return _result(score, recommendation, reasons[:3], rejected=False)


def _result(score: int, recommendation: str, reasons: list[str], *, rejected: bool) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "profile": _PROFILE,
        "score": score,
        "recommendation": recommendation,
        "reasons": reasons,
        "rejected": rejected,
    }


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _positive(value: object) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None
