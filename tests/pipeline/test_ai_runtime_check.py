import sys

from scripts.check_ai_runtime import _adtof_runtime_check, _true_pipeline_missing


def test_adtof_runtime_check_requires_explicit_template() -> None:
    result = _adtof_runtime_check(None, None)

    assert result["ready"] is False
    assert result["template_configured"] is False
    assert result["runtime_verified"] is False
    assert result["configured"] is False
    assert result["status_code"] == "not_configured"
    assert result["configuration_source"] == "default_adapter_template"
    assert result["missing_placeholders"] == []


def test_adtof_runtime_check_validates_template_placeholders() -> None:
    result = _adtof_runtime_check(f"{sys.executable} -m json.tool {{input}}", None)

    assert result["ready"] is False
    assert result["configured"] is True
    assert result["status_code"] == "template_invalid"
    assert result["missing_placeholders"] == ["output"]


def test_adtof_runtime_check_reports_missing_verify_input() -> None:
    result = _adtof_runtime_check(f"{sys.executable} -m json.tool {{input}} {{output}}", None)

    assert result["ready"] is False
    assert result["status_code"] == "verify_input_missing"
    assert result["output_verification"]["status_code"] == "verify_input_missing"


def test_adtof_runtime_check_reports_missing_verify_input_path(tmp_path) -> None:
    result = _adtof_runtime_check(
        f"{sys.executable} -m json.tool {{input}} {{output}}",
        None,
        verify_input=str(tmp_path / "missing-drums.wav"),
    )

    assert result["ready"] is False
    assert result["status_code"] == "verify_input_not_found"
    assert result["output_verification"]["status_code"] == "verify_input_not_found"


def test_adtof_runtime_check_reports_command_failure(tmp_path) -> None:
    drums_path = tmp_path / "drums.wav"
    drums_path.write_bytes(b"fake drums")
    template = f"{sys.executable} -c \"import sys; sys.exit(2)\" {{input}} {{output}}"

    result = _adtof_runtime_check(template, None, verify_input=str(drums_path))

    assert result["ready"] is False
    assert result["status_code"] == "command_failed"
    assert result["output_verification"]["status_code"] == "command_failed"


def test_adtof_runtime_check_does_not_accept_arbitrary_executable(tmp_path) -> None:
    drums_path = tmp_path / "drums.wav"
    drums_path.write_bytes(b"not real audio")

    result = _adtof_runtime_check(
        "echo {input} {output}",
        None,
        verify_input=str(drums_path),
    )

    assert result["template_configured"] is True
    assert result["template_executable"] is True
    assert result["output_verified"] is False
    assert result["runtime_verified"] is False
    assert result["ready"] is False
    assert result["status_code"] == "output_missing"
    assert result["output_verification"]["status_code"] == "output_missing"
    assert result["output_verification"]["reason"] == "raw_drum.mid was not created"


def test_adtof_runtime_check_reports_unparseable_raw_midi(tmp_path) -> None:
    drums_path = tmp_path / "drums.wav"
    drums_path.write_bytes(b"fake drums")
    writer_path = tmp_path / "write_bad_midi.py"
    writer_path.write_text(
        "from pathlib import Path\nimport sys\nPath(sys.argv[2]).write_bytes(b'not midi')\n",
        encoding="utf-8",
    )
    template = f"{sys.executable} {writer_path} {{input}} {{output}}"

    result = _adtof_runtime_check(template, None, verify_input=str(drums_path))

    assert result["ready"] is False
    assert result["status_code"] == "output_unparseable"
    assert result["output_verification"]["status_code"] == "output_unparseable"


def test_adtof_runtime_check_reports_raw_midi_without_events(tmp_path) -> None:
    drums_path = tmp_path / "drums.wav"
    drums_path.write_bytes(b"fake drums")
    writer_path = tmp_path / "write_empty_midi.py"
    writer_path.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "output = Path(sys.argv[2])",
                "track = b'\\x00\\xff\\x2f\\x00'",
                "data = bytearray()",
                "data.extend(b'MThd')",
                "data.extend((6).to_bytes(4, 'big'))",
                "data.extend((0).to_bytes(2, 'big'))",
                "data.extend((1).to_bytes(2, 'big'))",
                "data.extend((480).to_bytes(2, 'big'))",
                "data.extend(b'MTrk')",
                "data.extend(len(track).to_bytes(4, 'big'))",
                "data.extend(track)",
                "output.write_bytes(bytes(data))",
            ]
        ),
        encoding="utf-8",
    )
    template = f"{sys.executable} {writer_path} {{input}} {{output}}"

    result = _adtof_runtime_check(template, None, verify_input=str(drums_path))

    assert result["ready"] is False
    assert result["status_code"] == "output_no_events"
    assert result["output_verification"]["status_code"] == "output_no_events"
    assert result["output_verification"]["event_count"] == 0


def test_adtof_runtime_check_requires_verified_raw_midi_output(tmp_path) -> None:
    drums_path = tmp_path / "drums.wav"
    drums_path.write_bytes(b"fake drums")
    writer_path = tmp_path / "write_midi.py"
    writer_path.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "output = Path(sys.argv[2])",
                "output.parent.mkdir(parents=True, exist_ok=True)",
                "track = bytearray()",
                "track.extend(b'\\x00\\x90\\x24\\x40')",
                "track.extend(b'\\x83\\x60\\x80\\x24\\x00')",
                "track.extend(b'\\x00\\xff\\x2f\\x00')",
                "data = bytearray()",
                "data.extend(b'MThd')",
                "data.extend((6).to_bytes(4, 'big'))",
                "data.extend((0).to_bytes(2, 'big'))",
                "data.extend((1).to_bytes(2, 'big'))",
                "data.extend((480).to_bytes(2, 'big'))",
                "data.extend(b'MTrk')",
                "data.extend(len(track).to_bytes(4, 'big'))",
                "data.extend(track)",
                "output.write_bytes(bytes(data))",
            ]
        ),
        encoding="utf-8",
    )
    template = f"{sys.executable} {writer_path} {{input}} {{output}}"

    result = _adtof_runtime_check(template, None, verify_input=str(drums_path))

    assert result["template_configured"] is True
    assert result["template_executable"] is True
    assert result["output_verified"] is True
    assert result["runtime_verified"] is True
    assert result["ready"] is True
    assert result["status_code"] == "ready"
    assert result["output_verification"]["status_code"] == "ready"
    assert result["output_verification"]["event_count"] == 1


def test_true_pipeline_missing_lists_model_runtime_gaps() -> None:
    missing = _true_pipeline_missing(ffmpeg_ready=True, demucs_ready=False, adtof_ready=False)

    adtof_missing = (
        "ADTOF runtime has not produced and verified raw_drum.mid; "
        "set GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE and GROOVESCRIBE_ADTOF_VERIFY_INPUT "
        "for output verification"
    )
    assert missing == [
        "Demucs package/command probe is not ready",
        adtof_missing,
    ]
