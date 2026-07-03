from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a Demucs drums stem for GROOVESCRIBE_ADTOF_VERIFY_INPUT."
    )
    parser.add_argument("--input", type=Path, required=True, help="Full mix MP3/WAV input.")
    parser.add_argument("--normalized-dir", type=Path, default=Path("/tmp/groovescribe-normalized"))
    parser.add_argument("--stems-dir", type=Path, default=Path("/tmp/groovescribe-stems"))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--model-name", default="htdemucs")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running ffmpeg/Demucs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    normalize_command = [
        args.python,
        "scripts/run_normalize_audio.py",
        "--input",
        str(args.input),
        "--output-dir",
        str(args.normalized_dir),
    ]
    demucs_command = [
        args.python,
        "scripts/run_demucs_separation.py",
        "--input",
        str(args.normalized_dir / "normalized.wav"),
        "--output-dir",
        str(args.stems_dir),
        "--model-name",
        args.model_name,
        "--device",
        args.device,
    ]
    if args.dry_run:
        _print_payload(
            status="dry_run",
            normalize_command=normalize_command,
            demucs_command=demucs_command,
            drums_path=args.stems_dir / "drums.wav",
        )
        return 0

    normalized = _run_json_command(normalize_command)
    if normalized.get("status") != "completed":
        print(json.dumps({"status": "failed", "stage": "normalize", "result": normalized}, indent=2))
        return 1

    demucs = _run_json_command(demucs_command)
    if demucs.get("status") != "completed":
        print(json.dumps({"status": "failed", "stage": "demucs", "result": demucs}, indent=2))
        return 1

    drums_path = Path(str(demucs.get("drums_path") or args.stems_dir / "drums.wav"))
    _print_payload(
        status="completed",
        normalize_command=normalize_command,
        demucs_command=demucs_command,
        drums_path=drums_path,
    )
    return 0


def _run_json_command(command: list[str]) -> dict:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"status": "failed", "message": "command did not return JSON"}
    payload.setdefault("returncode", completed.returncode)
    return payload


def _print_payload(
    *,
    status: str,
    normalize_command: list[str],
    demucs_command: list[str],
    drums_path: Path,
) -> None:
    print(
        json.dumps(
            {
                "status": status,
                "normalize_command": normalize_command,
                "demucs_command": demucs_command,
                "drums_path": str(drums_path),
                "export": f"export GROOVESCRIBE_ADTOF_VERIFY_INPUT={drums_path}",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
