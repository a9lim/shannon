"""Reaction extraction from LLM response text."""

import re

_REACTION_PATTERN = re.compile(r"\[react:\s*([^\]]+)\]")


def extract_reactions(text: str) -> tuple[str, list[str]]:
    """Strip [react: emoji] markers from text and return (clean_text, reactions)."""
    reactions = _REACTION_PATTERN.findall(text)
    clean = _REACTION_PATTERN.sub("", text).strip()
    return clean, [r.strip() for r in reactions if r.strip()]
