from functools import lru_cache

from app.core.config import get_settings
from app.storage.base import StorageAdapter
from app.storage.local import LocalStorageAdapter


@lru_cache
def get_storage_adapter() -> StorageAdapter:
    settings = get_settings()
    return LocalStorageAdapter(settings.storage_root)
