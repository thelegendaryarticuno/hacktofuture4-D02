from __future__ import annotations

from typing import Iterable

FAILURE_KEYWORDS: tuple[str, ...] = (
    "error",
    "failed",
    "exception",
    "traceback",
    "exit code",
    "container failed to start",
    "exit 1",
)

NOISE_PREFIXES: tuple[str, ...] = (
    "=====",
    "time=",
)


def _clean_line(line: str) -> str:
    cleaned = line.strip()
    if not cleaned:
        return ""
    for prefix in NOISE_PREFIXES:
        if cleaned.lower().startswith(prefix):
            return ""
    return cleaned


def find_failure_line_indexes(lines: Iterable[str]) -> list[int]:
    indexed_lines = list(lines)
    indexes: list[int] = []
    for index, line in enumerate(indexed_lines):
        lower = line.lower()
        if any(keyword in lower for keyword in FAILURE_KEYWORDS):
            indexes.append(index)
    return indexes


def has_failure_signal(logs_text: str) -> bool:
    if not logs_text:
        return False
    return bool(find_failure_line_indexes(logs_text.splitlines()))


def extract_failure_snippet(logs_text: str, min_lines: int = 2, max_lines: int = 5) -> str:
    if not logs_text:
        return ""

    lines = logs_text.splitlines()
    matches = find_failure_line_indexes(lines)
    if not matches:
        return ""

    start = max(0, matches[0] - 1)
    end = min(len(lines), matches[-1] + 2)

    cleaned_lines = [_clean_line(line) for line in lines[start:end]]
    cleaned_lines = [line for line in cleaned_lines if line]

    if not cleaned_lines:
        return ""

    if len(cleaned_lines) < min_lines:
        fallback = [_clean_line(line) for line in lines[max(0, start - 2):min(len(lines), end + 2)]]
        cleaned_lines = [line for line in fallback if line]

    return "\n".join(cleaned_lines[:max_lines])
