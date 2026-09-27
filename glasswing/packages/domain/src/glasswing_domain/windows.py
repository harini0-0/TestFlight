"""Split long text into overlapping windows that each fit one model request."""

from __future__ import annotations

import re

BATCH_CHARS = 12_000
OVERLAP_CHARS = 800


def split_text(text: str, limit: int = BATCH_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Return windows in order. A short text is one window. Neighbors share an overlap so a clause on a cut is read twice."""
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= limit:
        return [cleaned]
    parts = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    windows: list[str] = []
    current = ""
    for part in parts:
        if len(part) > limit:
            if current:
                windows.append(current)
                current = ""
            windows.extend(_hard_windows(part, limit, overlap))
            continue
        candidate = part if not current else f"{current}\n\n{part}"
        if len(candidate) <= limit:
            current = candidate
            continue
        windows.append(current)
        tail = current[-overlap:].strip()
        current = f"{tail}\n\n{part}" if tail else part
    if current:
        windows.append(current)
    return windows


def _hard_windows(text: str, limit: int, overlap: int) -> list[str]:
    windows: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + limit)
        if end < len(text):
            break_at = text.rfind("\n", start + min(overlap, limit // 2), end)
            if break_at > start:
                end = break_at
        window = text[start:end].strip()
        if window:
            windows.append(window)
        if end >= len(text):
            break
        next_start = end - overlap
        start = end if next_start <= start else next_start
    return windows
