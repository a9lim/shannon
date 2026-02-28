"""System prompt builder for Shannon."""


class PromptBuilder:
    def __init__(self, personality_text: str, name: str = "Shannon") -> None:
        self._personality = personality_text
        self._name = name

    def build(self, memory_context: str = "", conversation_summary: str = "", suffix: str = "") -> str:
        """Build the complete system prompt."""
        parts = [self._personality]
        if memory_context:
            parts.append(f"\n\n{memory_context}")
        if conversation_summary:
            parts.append(f"\n\n## Earlier Conversation Summary\n{conversation_summary}")
        parts.append(
            "\n\n## Response Format\n"
            "Respond naturally as yourself. When you want to express an emotion, "
            "use the set_expression tool. When you want to run a shell command, use "
            "bash. When you need to interact with the screen, use computer. When you "
            "need to edit files, use str_replace_based_edit_tool. When you learn "
            "something worth remembering, use memory. When you need to look something "
            "up, use web_search."
        )
        if suffix:
            parts.append(f"\n\n{suffix}")
        return "\n".join(parts)
