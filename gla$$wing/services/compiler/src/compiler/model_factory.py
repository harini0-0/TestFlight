"""Picks a model backend based on GLASSWING_LLM:

  - "claude"    -> ClaudeModel, direct Anthropic API (needs ANTHROPIC_API_KEY)
  - "deepseek"  -> DeepSeekModel, DeepSeek/GLM via the hackathon's Sciforium
                   OpenAI-compatible proxy (needs OPENAI_COMPATIBLE_API_KEY,
                   and optionally OPENAI_COMPATIBLE_BASE_URL / SCIFORIUM_DEEPSEEK_MODEL)
  - anything else (including unset) -> RecordingModel, deterministic,
                   no network — this is what `make test` runs against, so it
                   stays offline and reproducible regardless of which real
                   backend is configured for a demo.
"""

from __future__ import annotations

import os

from compiler.recording_model import RecordingModel


def build_model(supplier_key: str, model_id: str = "anthropic.claude-sonnet"):
    backend = os.environ.get("GLASSWING_LLM")
    if backend == "claude":
        from compiler.claude_model import ClaudeModel

        return ClaudeModel(supplier_key, model_id)
    if backend == "deepseek":
        from compiler.deepseek_model import DeepSeekModel

        return DeepSeekModel(supplier_key)
    return RecordingModel(supplier_key, model_id)
