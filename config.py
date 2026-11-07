"""Single source of truth for model choices. Update models ONLY here.

Verify access for your own Google AI Studio project; published models do not
necessarily imply that a specific API key can invoke them.
"""
from __future__ import annotations

# A stable text model with a documented API free tier (subject to quotas).
DEFAULT_MODEL = "gemini-3.5-flash"
MODEL_OPTIONS = (
    DEFAULT_MODEL,
    "gemini-3.5-flash-lite",
)


def normalize_model(value: object) -> str:
    """Map discontinued/unknown checkpoint choices to the current default."""
    return value if isinstance(value, str) and value in MODEL_OPTIONS else DEFAULT_MODEL
