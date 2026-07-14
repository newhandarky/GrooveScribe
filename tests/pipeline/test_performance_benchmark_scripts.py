from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_script(name: str):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(name, root / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_is_skipped_without_external_manifest(tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    config = type("Config", (), {"manifest": None, "output_dir": tmp_path, "python": Path("python"), "adtof_command_template": None, "adtof_device": "cpu", "demucs_device": "cpu", "mock_ai": False})()

    report = script.run_benchmark(config)

    assert report["status"] == "skipped"
    assert report["summary"]["reason"] == "benchmark_manifest_not_provided"
    assert (tmp_path / "performance_benchmark_report.json").exists()
    assert not any(token in (tmp_path / "performance_benchmark_report.json").read_text(encoding="utf-8") for token in ("/tmp/", "/Users/", "command_template"))


def test_benchmark_parser_uses_configured_adtof_template(monkeypatch, tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    monkeypatch.setenv("GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE", "adtof --audio {input} --out {output}")
    monkeypatch.setattr(sys, "argv", ["benchmark", "--output-dir", str(tmp_path)])

    args = script.parse_args()

    assert args.adtof_command_template == "adtof --audio {input} --out {output}"


def test_benchmark_parser_accepts_product_preset_and_filter(monkeypatch, tmp_path: Path) -> None:
    script = _load_script("run_performance_benchmark")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark",
            "--output-dir",
            str(tmp_path),
            "--adtof-threshold-preset",
            "separated_v1",
            "--tom-filter-preset",
            "tom_guard_v1",
        ],
    )

    args = script.parse_args()

    assert args.adtof_threshold_preset == "separated_v1"
    assert args.tom_filter_preset == "tom_guard_v1"


def test_synthetic_generator_writes_external_manifest(monkeypatch, tmp_path: Path) -> None:
    script = _load_script("generate_performance_benchmark_fixtures")
    monkeypatch.setattr("sys.argv", ["generate", "--output-dir", str(tmp_path)])

    assert script.main() == 0
    manifest = json.loads((tmp_path / "performance_benchmark_manifest.json").read_text(encoding="utf-8"))
    assert {item["input_type"] for item in manifest["items"]} == {"drum_only", "full_mix"}
    assert all(Path(item["audio_path"]).exists() and Path(item["ground_truth_midi_path"]).exists() for item in manifest["items"])
