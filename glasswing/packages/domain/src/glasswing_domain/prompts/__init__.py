"""Prompt hashes stored on every extraction."""

from __future__ import annotations

import hashlib
from importlib import resources


def prompt_text(name: str) -> str:
    return resources.files("glasswing_domain.prompts").joinpath(name).read_text(encoding="utf-8")


def prompt_sha256(name: str) -> str:
    return hashlib.sha256(prompt_text(name).encode("utf-8")).hexdigest()
