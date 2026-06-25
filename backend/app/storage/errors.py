class StorageError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class StorageWriteFailedError(StorageError):
    def __init__(self, message: str = "storage write failed") -> None:
        super().__init__("STORAGE_WRITE_FAILED", message)


class StorageReadFailedError(StorageError):
    def __init__(self, message: str = "storage read failed") -> None:
        super().__init__("STORAGE_READ_FAILED", message)


class ArtifactNotFoundError(StorageError):
    def __init__(self, message: str = "artifact not found") -> None:
        super().__init__("ARTIFACT_NOT_FOUND", message)


class ArtifactInvalidError(StorageError):
    def __init__(self, message: str = "artifact is invalid") -> None:
        super().__init__("ARTIFACT_INVALID", message)


class PathTraversalRejectedError(StorageError):
    def __init__(self, message: str = "path traversal rejected") -> None:
        super().__init__("PATH_TRAVERSAL_REJECTED", message)
