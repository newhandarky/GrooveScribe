class MidiPostProcessingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RawMidiInvalidError(MidiPostProcessingError):
    def __init__(self, message: str = "raw MIDI is invalid") -> None:
        super().__init__("RAW_MIDI_INVALID", message)


class NoUsableDrumEventsError(MidiPostProcessingError):
    def __init__(self, message: str = "no usable drum events") -> None:
        super().__init__("NO_USABLE_DRUM_EVENTS", message)


class ProcessedMidiInvalidError(MidiPostProcessingError):
    def __init__(self, message: str = "processed MIDI is invalid") -> None:
        super().__init__("PROCESSED_MIDI_INVALID", message)


class MidiPostProcessingFailedError(MidiPostProcessingError):
    def __init__(self, message: str = "MIDI post-processing failed") -> None:
        super().__init__("MIDI_POST_PROCESSING_FAILED", message)
