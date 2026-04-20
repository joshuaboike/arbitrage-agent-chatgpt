from __future__ import annotations

import re

WHITESPACE_PATTERN = re.compile(r"\s+")
NUMBER_PATTERN = re.compile(r"(?P<value>\d+)\s*(?P<unit>tb|gb)")
SCREEN_PATTERN = re.compile(r"(?P<screen>\d{1,2}(?:\.\d)?)\s*(?:in|inch|\"|'')")


def normalize_text(*parts: str | None) -> str:
    raw = " ".join(part for part in parts if part)
    lowered = raw.lower()
    return WHITESPACE_PATTERN.sub(" ", lowered).strip()


def extract_storage_gb(text: str) -> int | None:
    matches = NUMBER_PATTERN.findall(text)
    for value, unit in matches:
        amount = int(value)
        if unit == "tb":
            amount *= 1024
        if amount in {64, 128, 256, 512, 1024, 2048, 4096}:
            return amount
    return None


def extract_ram_gb(text: str) -> int | None:
    matches = NUMBER_PATTERN.findall(text)
    for value, unit in matches:
        amount = int(value)
        if unit == "gb" and amount in {8, 12, 16, 24, 32, 64, 96, 128}:
            return amount
    return None


def extract_screen_size(text: str) -> str | None:
    match = SCREEN_PATTERN.search(text)
    if not match:
        return None
    return match.group("screen")
