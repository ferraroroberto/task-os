"""Local-hub AI features shared by inbox triage and later generated notes."""

from src.ai.client import AIClient, AIError
from src.ai.triage import (
    accept_suggestion,
    generate_suggestions,
    list_suggestions,
    reject_suggestion,
)

__all__ = [
    "AIClient",
    "AIError",
    "accept_suggestion",
    "generate_suggestions",
    "list_suggestions",
    "reject_suggestion",
]
