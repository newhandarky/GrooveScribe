from __future__ import annotations

from typing import Any

UNSAFE_PATH_TOKENS = (
    "/Users/",
    "/tmp/",
    "/private/tmp/",
    "/var/folders/",
)

UNSAFE_DIAGNOSTIC_TOKENS = (
    "traceback",
    "stdout",
    "stderr",
    "raw command",
    "command_template",
)


def find_unsafe_tokens(value: Any) -> list[str]:
    text = str(value)
    lowered = text.lower()
    found = [token for token in UNSAFE_PATH_TOKENS if token in text]
    found.extend(token for token in UNSAFE_DIAGNOSTIC_TOKENS if token in lowered)
    return sorted(set(found))


def is_public_safe(value: Any) -> bool:
    return not find_unsafe_tokens(value)
