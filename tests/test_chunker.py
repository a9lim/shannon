"""Tests for the message chunker."""

import pytest
from shannon.core.chunker import chunk_message


class TestChunkMessage:
    def test_short_message_single_chunk(self):
        result = chunk_message("Hello world", limit=100)
        assert result == ["Hello world"]

    def test_empty_message(self):
        result = chunk_message("", limit=100)
        assert result == [""]

    def test_splits_on_paragraph_boundary(self):
        text = "First paragraph.\n\nSecond paragraph."
        result = chunk_message(text, limit=25)
        assert len(result) == 2
        assert result[0] == "First paragraph."
        assert result[1] == "Second paragraph."

    def test_splits_on_sentence_boundary(self):
        text = "First sentence. Second sentence. Third sentence."
        result = chunk_message(text, limit=35)
        # Should split at sentence boundaries
        assert all(len(c) <= 35 for c in result)
        assert len(result) >= 2

    def test_preserves_code_blocks(self):
        text = "Here is code:\n\n```python\ndef hello():\n    print('world')\n```\n\nEnd."
        result = chunk_message(text, limit=2000)
        # Should be single chunk when under limit
        assert len(result) == 1
        assert "```python" in result[0]
        assert "```" in result[0]

    def test_splits_large_code_block(self):
        lines = [f"line {i}" for i in range(100)]
        code = "```\n" + "\n".join(lines) + "\n```"
        result = chunk_message(code, limit=200)
        # Each chunk should be a valid code block
        for chunk in result:
            assert chunk.startswith("```")
            assert chunk.endswith("```")

    def test_respects_limit(self):
        text = " ".join(["word"] * 500)
        limit = 100
        result = chunk_message(text, limit=limit)
        for chunk in result:
            assert len(chunk) <= limit

    def test_word_boundary_fallback(self):
        # Single very long word
        text = "a" * 50
        result = chunk_message(text, limit=20)
        assert all(len(c) <= 20 for c in result)

    def test_merges_short_chunks(self):
        text = "A.\n\nB.\n\nC."
        # With a high limit, short chunks should be merged
        result = chunk_message(text, limit=100)
        assert len(result) == 1

    def test_discord_limit(self):
        text = "x " * 2000  # ~4000 chars
        result = chunk_message(text, limit=1900)
        for chunk in result:
            assert len(chunk) <= 1900

    def test_signal_limit(self):
        text = "y " * 2000
        result = chunk_message(text, limit=2000)
        for chunk in result:
            assert len(chunk) <= 2000

    def test_clause_splitting(self):
        text = "first clause, second clause, third clause, fourth clause, fifth clause"
        result = chunk_message(text, limit=40)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 40

    def test_mixed_content(self):
        text = (
            "Here is some text.\n\n"
            "```python\nprint('hello')\n```\n\n"
            "More text after code."
        )
        result = chunk_message(text, limit=2000)
        full = "\n".join(result)
        assert "print('hello')" in full
        assert "More text after code." in full
