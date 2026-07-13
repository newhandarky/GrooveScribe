from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


ARTIFACTS = {
    "processed_drum.mid": "midi/processed_drum.mid",
    "score.musicxml": "notation/score.musicxml",
    "chart_events.json": "notation/chart_events.json",
    "pipeline.json": "logs/pipeline.json",
}
OPTIONAL_ARTIFACTS = {
    "score.pdf": "exports/score.pdf",
    "score_preview.png": "exports/score_preview.png",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy a readable-chart run into a durable QA folder with a manifest")
    parser.add_argument("--pipeline-output-dir", type=Path, required=True)
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument("--run-name", required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    source_root = args.pipeline_output_dir.resolve()
    run_dir = args.export_dir.resolve() / args.run_name
    if run_dir.exists():
        raise SystemExit(f"export run already exists: {run_dir.name}")

    sources = {name: source_root / relative_path for name, relative_path in ARTIFACTS.items()}
    missing = [name for name, path in sources.items() if not path.is_file()]
    if missing:
        raise SystemExit(f"missing required artifacts: {', '.join(missing)}")
    sources.update(
        {
            name: source_root / relative_path
            for name, relative_path in OPTIONAL_ARTIFACTS.items()
            if (source_root / relative_path).is_file()
        }
    )

    run_dir.mkdir(parents=True)
    manifest_files = []
    for filename, source in sources.items():
        destination = run_dir / filename
        shutil.copy2(source, destination)
        manifest_files.append(
            {
                "name": filename,
                "bytes": destination.stat().st_size,
                "sha256": _sha256(destination),
            }
        )
    manifest = {
        "schema_version": "1.0",
        "run_name": args.run_name,
        "files": manifest_files,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "completed", "run_name": args.run_name, "files": manifest_files}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
