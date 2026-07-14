from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_pipeline.notation.performance_gate import compare_performance_midi_to_ground_truth, evaluate_performance_score


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a GrooveScribe performance-score delivery artifact")
    parser.add_argument("--chart-events", type=Path, required=True)
    parser.add_argument("--performance-midi", type=Path, required=True)
    parser.add_argument("--performance-musicxml", type=Path, required=True)
    parser.add_argument("--drums-stem", type=Path, default=None)
    parser.add_argument("--ground-truth-midi", type=Path, default=None, help="Optional authorized reference drum MIDI")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gate = evaluate_performance_score(
        chart_events_path=args.chart_events,
        performance_midi_path=args.performance_midi,
        performance_musicxml_path=args.performance_musicxml,
        drums_stem_path=args.drums_stem,
    )
    ground_truth = (
        compare_performance_midi_to_ground_truth(args.performance_midi, args.ground_truth_midi)
        if args.ground_truth_midi is not None and args.ground_truth_midi.exists()
        else {"status": "not_provided", "precision": None, "recall": None, "f1": None}
    )
    report = {"schema_version": "1.0", "performance_gate": gate, "ground_truth_eval": ground_truth}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": gate["verdict"], "report_name": args.output.name}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
