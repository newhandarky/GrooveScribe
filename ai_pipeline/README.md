# AI Pipeline

Local Python package for the GrooveScribe audio pipeline.

## MVP Pipeline

1. Normalize MP3/WAV into `normalized.wav` with ffmpeg.
2. Split the full song into a `drums.wav` stem with Demucs.
3. Transcribe `drums.wav` into `raw_drum.mid` with ADTOF-pytorch.
4. Quantize and map MIDI notes into `processed_drum.mid`.
5. Generate `drum_score.musicxml` and `drum_score.pdf` for preview and download.

## Current Scope

This scaffold covers `GS-P1-001` only:

- Shared pipeline stage contract.
- Local pipeline plan builder.
- Dry-run CLI entry point under `scripts/run_local_pipeline.py`.

ffmpeg normalization and the Demucs source-separation adapter are now implemented as local POC modules. ADTOF-pytorch, MIDI post-processing, and notation rendering will be added in later tickets.

## Smoke Command

```bash
PYTHONPATH=. python scripts/run_local_pipeline.py --output-dir storage/local/jobs/dev-smoke
PYTHONPATH=. python scripts/run_normalize_audio.py --input /path/to/audio.wav --output-dir /tmp/groovescribe-normalized
PYTHONPATH=. python scripts/run_demucs_separation.py --input /tmp/groovescribe-normalized/normalized.wav --output-dir /tmp/groovescribe-stems
```
