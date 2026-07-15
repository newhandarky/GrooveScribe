from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a private, source-isolated GMD training manifest.")
    parser.add_argument("--gmd-root", type=Path, required=True, help="Directory containing GMD's groove/info.csv.")
    parser.add_argument("--benchmark-manifest", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--max-train-items", type=int, default=120)
    parser.add_argument("--max-validation-items", type=int, default=30)
    return parser.parse_args()


def build_manifest(config: argparse.Namespace) -> dict[str, Any]:
    root = config.gmd_root.expanduser().resolve()
    info_path = root / "info.csv"
    benchmark = _read_json(config.benchmark_manifest)
    benchmark_sources = _benchmark_source_ids(benchmark)
    if not info_path.is_file():
        return {"status": "blocked", "reason_code": "gmd_info_missing"}

    rows = list(csv.DictReader(info_path.read_text(encoding="utf-8").splitlines()))
    available = sorted({str(row.get("drummer") or "") for row in rows if row.get("drummer")})
    usable_sources = [source for source in available if source not in benchmark_sources]
    if len(usable_sources) < 2:
        return {"status": "blocked", "reason_code": "source_isolated_training_data_insufficient"}
    validation_source = usable_sources[-1]
    train_sources = usable_sources[:-1]
    items = []
    for row in rows:
        source_id = str(row.get("drummer") or "")
        if source_id not in train_sources + [validation_source] or row.get("split") not in {"train", "validation"}:
            continue
        audio = root / str(row.get("audio_filename") or "")
        midi = root / str(row.get("midi_filename") or "")
        if not audio.is_file() or not midi.is_file():
            continue
        items.append(
            {
                "id": str(row.get("id") or audio.stem),
                "source_id": source_id,
                "split": "validation" if source_id == validation_source else "train",
                "audio_path": str(audio),
                "ground_truth_midi_path": str(midi),
                "tempo_bpm": float(row.get("bpm") or 120),
                "time_signature": str(row.get("time_signature") or "4-4").replace("-", "/"),
                "style": str(row.get("style") or "unknown"),
            }
        )
    train = [item for item in items if item["split"] == "train"][: max(0, config.max_train_items)]
    validation = [item for item in items if item["split"] == "validation"][: max(0, config.max_validation_items)]
    if not train or not validation:
        return {"status": "blocked", "reason_code": "source_isolated_training_data_insufficient"}
    payload = {
        "schema_version": "1.0",
        "status": "completed",
        "dataset": "Google Magenta Groove MIDI Dataset",
        "license": "CC BY 4.0",
        "source_id_policy": "drummer",
        "benchmark_source_ids": sorted(benchmark_sources),
        "training_source_ids": train_sources,
        "validation_source_ids": [validation_source],
        "source_id_overlap_with_benchmark": False,
        "items": train + validation,
        "summary": {"train_item_count": len(train), "validation_item_count": len(validation)},
    }
    config.output_manifest.parent.mkdir(parents=True, exist_ok=True)
    config.output_manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _benchmark_source_ids(payload: dict[str, Any]) -> set[str]:
    result = set()
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        parts = Path(str(item.get("audio_path") or "")).parts
        result.update(part for part in parts if part.startswith("drummer"))
    return result


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    report = build_manifest(parse_args())
    print(json.dumps({"status": report["status"], "reason_code": report.get("reason_code")}, ensure_ascii=False))
