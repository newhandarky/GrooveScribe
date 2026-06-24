class AudioPreprocessingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FfmpegNotAvailableError(AudioPreprocessingError):
    def __init__(self, message: str = "ffmpeg is not available") -> None:
        super().__init__("FFMPEG_NOT_AVAILABLE", message)


class AudioDecodeFailedError(AudioPreprocessingError):
    def __init__(self, message: str = "audio decode failed") -> None:
        super().__init__("AUDIO_DECODE_FAILED", message)


class PreprocessingTimeoutError(AudioPreprocessingError):
    def __init__(self, message: str = "audio preprocessing timed out") -> None:
        super().__init__("PREPROCESSING_TIMEOUT", message)


class NormalizedAudioInvalidError(AudioPreprocessingError):
    def __init__(self, message: str = "normalized audio is invalid") -> None:
        super().__init__("NORMALIZED_AUDIO_INVALID", message)
