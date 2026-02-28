"""Tests for reaction extraction from LLM output."""

from shannon.brain.reactions import extract_reactions


class TestExtractReactions:
    def test_no_reactions(self):
        clean, reactions = extract_reactions("Hello world")
        assert clean == "Hello world"
        assert reactions == []

    def test_single_reaction(self):
        clean, reactions = extract_reactions("Great message [react: 👍]")
        assert clean == "Great message"
        assert reactions == ["👍"]

    def test_multiple_reactions(self):
        clean, reactions = extract_reactions("Nice [react: 👍] [react: 🎉]")
        assert clean == "Nice"
        assert reactions == ["👍", "🎉"]

    def test_reaction_with_spaces(self):
        clean, reactions = extract_reactions("Ok [react:  😊  ]")
        assert clean == "Ok"
        assert reactions == ["😊"]

    def test_empty_reaction_ignored(self):
        clean, reactions = extract_reactions("Test [react: ]")
        assert clean == "Test"
        assert reactions == []

    def test_reaction_only_message(self):
        clean, reactions = extract_reactions("[react: 👍]")
        assert clean == ""
        assert reactions == ["👍"]

    def test_empty_input(self):
        clean, reactions = extract_reactions("")
        assert clean == ""
        assert reactions == []
