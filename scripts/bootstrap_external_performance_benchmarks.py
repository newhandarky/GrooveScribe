from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import mido

from ai_pipeline.midi.mapping import map_to_general_midi_drum
from ai_pipeline.midi.simple_midi import parse_midi


GMD_LICENSE = "CC BY 4.0"
GMD_LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
GMD_SOURCE = "Google Magenta Groove MIDI Dataset"
GMD_RELEASE = "groove-v1.0.0"
SLAKH_LICENSE = "CC BY 4.0"
SLAKH_LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
SLAKH_SOURCE = "BabySlakh / Slakh2100"
SLAKH_RELEASE = "BabySlakh v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a private manifest from licensed GMD and BabySlakh roots.")
    parser.add_argument("--gmd-root", type=Path, required=True)
    parser.add_argument("--slakh-root", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--gmd-limit", type=int, default=12)
    parser.add_argument("--slakh-limit", type=int, default=12)
    return parser.parse_args()


def bootstrap(config: argparse.Namespace) -> dict[str, Any]:
    gmd_items, gmd_reason = _collect_gmd(config.gmd_root, limit=config.gmd_limit)
    slakh_items, slakh_reason = _collect_slakh(config.slakh_root, limit=config.slakh_limit)
    status = "completed" if len(gmd_items) >= config.gmd_limit and len(slakh_items) >= config.slakh_limit else "blocked"
    manifest = {
        "schema_version": "1.1",
        "kind": "external_licensed_performance_benchmark",
        "private_manifest": True,
        "items": [*gmd_items, *slakh_items],
    }
    if status == "completed":
        config.output_manifest.parent.mkdir(parents=True, exist_ok=True)
        config.output_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "schema_version": "1.0",
        "status": status,
        "manifest_name": config.output_manifest.name if status == "completed" else None,
        "gmd_selected_count": len(gmd_items),
        "slakh_selected_count": len(slakh_items),
        "gmd_reason": gmd_reason,
        "slakh_reason": slakh_reason,
    }


def _collect_gmd(root: Path, *, limit: int) -> tuple[list[dict[str, Any]], str | None]:
    info_path = _find_one(root, "info.csv")
    if info_path is None:
        return [], "gmd_info_csv_missing"
    rows = list(csv.DictReader(info_path.read_text(encoding="utf-8").splitlines()))
    candidates = []
    for row in rows:
        audio = _resolve_dataset_path(root, row.get("audio_filename"))
        midi = _resolve_dataset_path(root, row.get("midi_filename"))
        if audio is None or midi is None:
            continue
        tags = _gmd_tags(midi, _number(row.get("bpm"), 120.0))
        candidates.append((row, audio, midi, tags))
    selected = _diverse_select(candidates, limit=limit, tag_getter=lambda item: item[3])
    items = []
    for index, (row, audio, midi, tags) in enumerate(selected, start=1):
        tempo = _number(row.get("bpm"), 120.0)
        time_signature = _time_signature(row.get("time_signature"), fallback="4/4")
        source_id = str(row.get("id") or midi.stem)
        items.append(
            _item(
                item_id=f"gmd-{index:02d}-{_safe_id(source_id)}",
                audio=audio,
                midi=midi,
                tempo_bpm=tempo,
                time_signature=time_signature,
                input_type="drum_only",
                source=GMD_SOURCE,
                source_release=GMD_RELEASE,
                license_name=GMD_LICENSE,
                license_url=GMD_LICENSE_URL,
                usage_scope="licensed_ground_truth_drum_only",
                tags=tags,
                metadata={
                    "style": _safe_text(row.get("style")),
                    "drummer": _safe_text(row.get("drummer")),
                    "session": _safe_text(row.get("session")),
                    "source_id": source_id,
                },
                synthetic_full_mix=False,
            )
        )
    return items, None if len(items) >= limit else "gmd_insufficient_valid_pairs"


def _collect_slakh(root: Path, *, limit: int) -> tuple[list[dict[str, Any]], str | None]:
    try:
        import yaml
    except ImportError:
        return [], "slakh_yaml_parser_unavailable"
    tracks = sorted(path for path in root.rglob("metadata.yaml") if path.parent.name.startswith("Track"))
    items = []
    for metadata_path in tracks:
        track = metadata_path.parent
        mix = _find_one(track, "mix.wav") or _find_one(track, "mix.flac")
        if mix is None:
            continue
        try:
            metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        drum_stems = _slakh_drum_stems(metadata)
        if not drum_stems:
            continue
        midi_paths = [track / "MIDI" / f"{stem}.mid" for stem in drum_stems]
        if not all(path.exists() for path in midi_paths):
            continue
        merged = track / ".groovescribe-benchmark-drums.mid"
        _merge_drum_midis(midi_paths, merged)
        tempo, time_signature = _midi_timing(merged)
        track_id = track.name
        items.append(
            _item(
                item_id=f"slakh-{track_id.lower()}",
                audio=mix,
                midi=merged,
                tempo_bpm=tempo,
                time_signature=time_signature,
                input_type="full_mix",
                source=SLAKH_SOURCE,
                source_release=SLAKH_RELEASE,
                license_name=SLAKH_LICENSE,
                license_url=SLAKH_LICENSE_URL,
                usage_scope="licensed_synthetic_full_mix_ground_truth",
                tags=["synthetic_full_mix"],
                metadata={"source_id": track_id, "drum_stem_ids": drum_stems},
                synthetic_full_mix=True,
            )
        )
        if len(items) >= limit:
            break
    return items, None if len(items) >= limit else "slakh_insufficient_valid_pairs"


def _item(
    *,
    item_id: str,
    audio: Path,
    midi: Path,
    tempo_bpm: float,
    time_signature: str,
    input_type: str,
    source: str,
    source_release: str,
    license_name: str,
    license_url: str,
    usage_scope: str,
    tags: list[str],
    metadata: dict[str, Any],
    synthetic_full_mix: bool,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "audio_path": str(audio.resolve()),
        "ground_truth_midi_path": str(midi.resolve()),
        "tempo_bpm": round(tempo_bpm, 3),
        "time_signature": time_signature,
        "input_type": input_type,
        "license": license_name,
        "license_url": license_url,
        "source": source,
        "source_release": source_release,
        "renderer": "dataset_recording" if input_type == "drum_only" else "sampled_drum_renderer",
        "sha256": {"audio": _sha256(audio), "ground_truth_midi": _sha256(midi)},
        "usage_scope": usage_scope,
        "calibration_eligible": True,
        "ground_truth_verified": True,
        "synthetic_full_mix": synthetic_full_mix,
        "real_audio_verified": not synthetic_full_mix,
        "selection_tags": tags,
        "source_metadata": metadata,
        "acceptance": {
            "minimum_f1": 0.75,
            "minimum_per_drum_f1": {"kick": 0.70, "snare": 0.70, "closed_hat": 0.60},
            "minimum_core_groove_accuracy": 0.70,
            "maximum_mean_timing_error_ticks": 72,
        },
    }


def _gmd_tags(midi_path: Path, tempo: float) -> list[str]:
    try:
        parsed = parse_midi(midi_path)
    except Exception:
        return ["unknown"]
    mapped = [(note.tick, map_to_general_midi_drum(note.note)) for note in parsed.notes]
    tags = ["fast_tempo" if tempo >= 140 else "slow_or_medium_tempo"]
    hats = sorted(tick for tick, drum in mapped if drum is not None and drum.drum in {"closed_hat", "open_hat"})
    if len(hats) >= 4:
        deltas = [right - left for left, right in zip(hats, hats[1:]) if right > left]
        median = sorted(deltas)[len(deltas) // 2] if deltas else parsed.ticks_per_beat
        tags.append("eighth_hat" if median <= parsed.ticks_per_beat * 0.75 else "quarter_hat")
    snare_ticks = {tick % (parsed.ticks_per_beat * 4) for tick, drum in mapped if drum is not None and drum.drum == "snare"}
    if parsed.ticks_per_beat in snare_ticks or parsed.ticks_per_beat * 3 in snare_ticks:
        tags.append("backbeat")
    tom_ticks = [tick for tick, drum in mapped if drum is not None and drum.drum == "tom"]
    if len(tom_ticks) >= 3:
        tags.append("tom_fill")
    return tags


def _diverse_select(candidates: list[Any], *, limit: int, tag_getter) -> list[Any]:
    wanted = ["eighth_hat", "quarter_hat", "backbeat", "tom_fill", "fast_tempo"]
    selected: list[Any] = []
    seen: set[str] = set()
    for tag in wanted:
        candidate = next((item for item in candidates if tag in tag_getter(item) and str(item[1]) not in seen), None)
        if candidate is not None:
            selected.append(candidate)
            seen.add(str(candidate[1]))
    for candidate in candidates:
        if len(selected) >= limit:
            break
        if str(candidate[1]) not in seen:
            selected.append(candidate)
            seen.add(str(candidate[1]))
    return selected[:limit]


def _slakh_drum_stems(metadata: object) -> list[str]:
    stems = metadata.get("stems") if isinstance(metadata, dict) else {}
    return sorted(
        str(stem_id)
        for stem_id, details in stems.items()
        # BabySlakh metadata may retain midi_saved=false even though its packaged
        # MIDI/Sxx.mid file is present. Existence is checked by the caller.
        if isinstance(details, dict) and details.get("is_drum") is True
    )


def _merge_drum_midis(paths: list[Path], output: Path) -> None:
    absolute: list[tuple[int, mido.Message]] = []
    timing_messages: list[tuple[int, mido.MetaMessage]] = []
    ticks_per_beat: int | None = None
    seen_timing_types: set[str] = set()
    for path in paths:
        midi = mido.MidiFile(path)
        if ticks_per_beat is None:
            ticks_per_beat = midi.ticks_per_beat
        elif midi.ticks_per_beat != ticks_per_beat:
            raise ValueError("slakh_drum_midi_ticks_per_beat_mismatch")
        for track in midi.tracks:
            tick = 0
            for message in track:
                tick += message.time
                if (
                    message.is_meta
                    and message.type in {"set_tempo", "time_signature"}
                    and message.type not in seen_timing_types
                ):
                    timing_messages.append((tick, message.copy(time=0)))
                    seen_timing_types.add(message.type)
                elif not message.is_meta and message.type in {"note_on", "note_off"}:
                    absolute.append((tick, message.copy(time=0, channel=9)))
    output.parent.mkdir(parents=True, exist_ok=True)
    merged = mido.MidiFile(ticks_per_beat=ticks_per_beat or 480)
    track = mido.MidiTrack()
    merged.tracks.append(track)
    previous = 0
    for tick, message in sorted([*timing_messages, *absolute], key=lambda item: (item[0], item[1].is_meta is False)):
        track.append(message.copy(time=max(0, tick - previous)))
        previous = tick
    track.append(mido.MetaMessage("end_of_track", time=0))
    merged.save(output)


def _midi_timing(path: Path) -> tuple[float, str]:
    midi = mido.MidiFile(path)
    tempo, signature = 500000, "4/4"
    for message in midi.merged_track:
        if message.type == "set_tempo":
            tempo = message.tempo
        if message.type == "time_signature":
            signature = f"{message.numerator}/{message.denominator}"
    return round(mido.tempo2bpm(tempo), 3), signature


def _resolve_dataset_path(root: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    direct = root / value
    if direct.exists():
        return direct
    matches = list(root.rglob(Path(value).name))
    return matches[0] if len(matches) == 1 else None


def _find_one(root: Path, name: str) -> Path | None:
    direct = root / name
    if direct.exists():
        return direct
    matches = list(root.rglob(name)) if root.exists() else []
    return matches[0] if len(matches) == 1 else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value: object, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) and number > 0 else fallback


def _time_signature(value: object, *, fallback: str) -> str:
    text = str(value or fallback).replace("-", "/")
    try:
        numerator, denominator = (int(item) for item in text.split("/", 1))
    except ValueError:
        return fallback
    return text if numerator > 0 and denominator > 0 else fallback


def _safe_id(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "-" for character in value).strip("-")[:80] or "item"


def _safe_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:160] or None


if __name__ == "__main__":
    report = bootstrap(parse_args())
    print(json.dumps(report, ensure_ascii=False))
