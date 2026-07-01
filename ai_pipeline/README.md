# AI Pipeline

Local Python package for the GrooveScribe audio pipeline.

## MVP Pipeline

1. Normalize MP3/WAV into `normalized.wav` with ffmpeg.
2. Split the full song into a `drums.wav` stem with Demucs.
3. Transcribe `drums.wav` into `raw_drum.mid` with ADTOF-pytorch.
4. Quantize and map MIDI notes into `processed_drum.mid`.
5. Generate `drum_score.musicxml` and `drum_score.pdf` for preview and download.

## Current Scope

This package now covers the Phase 1 POC code path with a clear mock/true-runtime split:

- Shared pipeline stage contract.
- ffmpeg normalization script and adapter.
- Demucs source-separation adapter boundary.
- ADTOF drum-transcription adapter boundary with configurable command template.
- Initial MIDI post-processing and drum event JSON.
- MusicXML generation and optional MuseScore PDF export.
- Local runner that can complete with `--mock-ai` or with the configured true Demucs / ADTOF runtime.

The Phase 1 runtime POC has been closed out in the local `.venv-ai` environment. True Demucs / ADTOF smoke has been run against generated synthetic fixtures and an authorized real-drum fixture; PDF artifact smoke passes with `completed_with_warning` when MuseScore creates a non-empty PDF but exits non-zero. Run `scripts/check_ai_runtime.py` first; it reports packages, commands, ADTOF template/output verification, and whether a non-mock local pipeline is ready. See `ai_pipeline/RUNTIME.md` for the exact versions, commands, artifacts, and remaining quality limitations.

## Smoke Command

```bash
export PYTHON="$(pwd)/.venv-ai/bin/python"
export GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE="$(pwd)/.venv-ai/bin/adtof --audio {input} --out {output} --device {device} --threshold {threshold}"
PYTHONPATH=. "$PYTHON" scripts/check_ai_runtime.py
PYTHONPATH=. "$PYTHON" scripts/run_local_pipeline.py --dry-run --output-dir storage/local/jobs/dev-smoke
PYTHONPATH=. "$PYTHON" scripts/run_local_pipeline.py --input /path/to/audio.wav --output-dir /tmp/groovescribe-job --mock-ai
PYTHONPATH=. "$PYTHON" scripts/run_normalize_audio.py --input /path/to/audio.wav --output-dir /tmp/groovescribe-normalized
PYTHONPATH=. "$PYTHON" scripts/run_demucs_separation.py --input /tmp/groovescribe-normalized/normalized.wav --output-dir /tmp/groovescribe-stems
PYTHONPATH=. "$PYTHON" scripts/run_adtof_transcription.py --input /tmp/groovescribe-stems/drums.wav --output-dir /tmp/groovescribe-midi --command-template "$GROOVESCRIBE_ADTOF_COMMAND_TEMPLATE"
PYTHONPATH=. "$PYTHON" scripts/run_midi_postprocess.py --input /tmp/groovescribe-midi/raw_drum.mid --output-dir /tmp/groovescribe-processed-midi
PYTHONPATH=. "$PYTHON" scripts/generate_score.py --events-json /tmp/groovescribe-processed-midi/drum_events.json --output-dir /tmp/groovescribe-score
```
