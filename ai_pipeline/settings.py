from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PipelineSettings:
    output_dir: Path
    ffmpeg_binary: str = "ffmpeg"
    source_separator: str = "demucs"
    drum_transcriber: str = "adtof-pytorch"
    notation_renderer: str = "music21"
