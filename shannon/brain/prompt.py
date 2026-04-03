"""System prompt builder for Shannon."""


class PromptBuilder:
    def __init__(self, personality_text: str, name: str = "Shannon") -> None:
        self._personality = personality_text
        self._name = name

    def build(self, memory_context: str = "", conversation_summary: str = "") -> str:
        """Build the complete system prompt (static content only for caching)."""
        parts = [self._personality]
        if memory_context:
            parts.append(f"\n\n{memory_context}")
        if conversation_summary:
            parts.append(f"\n\n## Earlier Conversation Summary\n{conversation_summary}")
        return "\n".join(parts)
