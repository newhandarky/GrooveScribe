class DrumTranscriptionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DrumTranscriberNotAvailableError(DrumTranscriptionError):
    def __init__(self, message: str = "drum transcriber is not available") -> None:
        super().__init__("DRUM_TRANSCRIBER_NOT_AVAILABLE", message)


class DrumTranscriptionFailedError(DrumTranscriptionError):
    def __init__(self, message: str = "drum transcription failed") -> None:
        super().__init__("DRUM_TRANSCRIPTION_FAILED", message)


class RawMidiNotFoundError(DrumTranscriptionError):
    def __init__(self, message: str = "raw MIDI was not found") -> None:
        super().__init__("RAW_MIDI_NOT_FOUND", message)


class RawMidiInvalidError(DrumTranscriptionError):
    def __init__(self, message: str = "raw MIDI is invalid") -> None:
        super().__init__("RAW_MIDI_INVALID", message)


class RawMidiEmptyError(DrumTranscriptionError):
    def __init__(self, message: str = "raw MIDI has no usable drum events") -> None:
        super().__init__("RAW_MIDI_EMPTY", message)
