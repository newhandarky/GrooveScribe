from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PipelineStage:
    name: str
    input_artifact: str
    output_artifact: str
    adapter: str


@dataclass(frozen=True)
class PipelinePlan:
    input_path: Path | None
    output_dir: Path
    stages: tuple[PipelineStage, ...]
