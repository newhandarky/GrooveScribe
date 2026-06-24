from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_pipeline.notation import MusicXmlGenerator, MuseScorePdfExporter, NotationConfig, NotationError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate MusicXML and optionally PDF from drum_events.json")
    parser.add_argument("--events-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--title", default="GrooveScribe Drum Draft")
    parser.add_argument("--export-pdf", action="store_true")
    parser.add_argument("--require-pdf", action="store_true")
    parser.add_argument("--pdf-renderer", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generator = MusicXmlGenerator(NotationConfig(title=args.title))

    try:
        musicxml = generator.generate(args.events_json, args.output_dir)
    except NotationError as exc:
        print(json.dumps({"status": "failed", "code": exc.code, "message": exc.message}, indent=2))
        return 1

    pdf_payload = {"status": "skipped"}
    if args.export_pdf or args.require_pdf:
        try:
            pdf = MuseScorePdfExporter(renderer_binary=args.pdf_renderer).export(
                musicxml.musicxml_path,
                args.output_dir,
            )
            pdf_payload = {"status": "completed", "pdf_path": str(pdf.pdf_path), "renderer": pdf.renderer}
        except NotationError as exc:
            pdf_payload = {"status": "failed", "code": exc.code, "message": exc.message}
            if args.require_pdf:
                print(
                    json.dumps(
                        {
                            "status": "failed",
                            "musicxml_path": str(musicxml.musicxml_path),
                            "pdf": pdf_payload,
                        },
                        indent=2,
                    )
                )
                return 1

    print(
        json.dumps(
            {
                "status": "completed",
                "musicxml_path": str(musicxml.musicxml_path),
                "event_count": musicxml.event_count,
                "measure_count": musicxml.measure_count,
                "pdf": pdf_payload,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
