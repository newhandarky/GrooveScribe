class NotationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NotationGenerationFailedError(NotationError):
    def __init__(self, message: str = "notation generation failed") -> None:
        super().__init__("NOTATION_GENERATION_FAILED", message)


class MusicXmlInvalidError(NotationError):
    def __init__(self, message: str = "MusicXML is invalid") -> None:
        super().__init__("MUSICXML_INVALID", message)


class PdfRendererNotAvailableError(NotationError):
    def __init__(self, message: str = "PDF renderer is not available") -> None:
        super().__init__("PDF_RENDERER_NOT_AVAILABLE", message)


class PdfExportFailedError(NotationError):
    def __init__(self, message: str = "PDF export failed") -> None:
        super().__init__("PDF_EXPORT_FAILED", message)
