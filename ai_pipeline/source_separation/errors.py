class SourceSeparationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SourceSeparatorNotAvailableError(SourceSeparationError):
    def __init__(self, message: str = "source separator is not available") -> None:
        super().__init__("SOURCE_SEPARATOR_NOT_AVAILABLE", message)


class SourceSeparationFailedError(SourceSeparationError):
    def __init__(self, message: str = "source separation failed") -> None:
        super().__init__("SOURCE_SEPARATION_FAILED", message)


class DrumsStemNotFoundError(SourceSeparationError):
    def __init__(self, message: str = "drums stem was not found") -> None:
        super().__init__("DRUMS_STEM_NOT_FOUND", message)


class DrumsStemInvalidError(SourceSeparationError):
    def __init__(self, message: str = "drums stem is invalid") -> None:
        super().__init__("DRUMS_STEM_INVALID", message)
