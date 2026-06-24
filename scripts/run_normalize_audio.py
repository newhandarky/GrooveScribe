from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_pipeline.preprocessing import AudioPreprocessingError, FfmpegAudioNormalizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize MP3/WAV into normalized.wav")
    parser.add_argument("--input", type=Path, required=True, help="Source MP3/WAV path")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output artifact directory")
    parser.add_argument("--sample-rate", type=int, default=44_100)
    parser.add_argument("--channels", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    normalizer = FfmpegAudioNormalizer(timeout_seconds=args.timeout_seconds)

    try:
        result = normalizer.normalize(
            input_path=args.input,
            output_dir=args.output_dir,
            target_sample_rate=args.sample_rate,
            channels=args.channels,
        )
    except AudioPreprocessingError as exc:
        print(json.dumps({"status": "failed", "code": exc.code, "message": exc.message}, indent=2))
        return 1

    print(
        json.dumps(
            {
                "status": "completed",
                "normalized_path": str(result.normalized_path),
                "metadata": {
                    "duration_seconds": result.metadata.duration_seconds,
                    "sample_rate": result.metadata.sample_rate,
                    "channels": result.metadata.channels,
                    "format": result.metadata.format,
                    "ffmpeg_version": result.metadata.ffmpeg_version,
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
