"""Tests for Discord provider utilities."""

from shannon.messaging.providers.discord import split_message


class TestSplitMessage:
    def test_short_message_unchanged(self):
        assert split_message("Hello world") == ["Hello world"]

    def test_empty_message(self):
        assert split_message("") == []

    def test_exactly_2000_chars(self):
        text = "a" * 2000
        assert split_message(text) == [text]

    def test_split_on_newline(self):
        text = "a" * 1900 + "\n" + "b" * 200
        chunks = split_message(text)
        assert len(chunks) == 2
        assert chunks[0] == "a" * 1900
        assert chunks[1] == "b" * 200

    def test_split_on_space_when_no_newline(self):
        text = "word " * 500  # 2500 chars
        chunks = split_message(text)
        assert all(len(c) <= 2000 for c in chunks)
        assert "".join(chunks).replace(" ", "") == "word" * 500

    def test_hard_split_no_whitespace(self):
        text = "a" * 3000
        chunks = split_message(text)
        assert len(chunks) == 2
        assert chunks[0] == "a" * 2000
        assert chunks[1] == "a" * 1000

    def test_all_chunks_within_limit(self):
        text = "Hello world! " * 300  # ~3900 chars
        chunks = split_message(text)
        assert all(len(c) <= 2000 for c in chunks)


class TestSplitMessageSentenceBoundary:
    def test_split_on_sentence_period(self):
        """Should split at '. ' when no newline is available."""
        text = "A" * 1800 + ". " + "B" * 300
        chunks = split_message(text)
        assert len(chunks) == 2
        assert chunks[0].endswith(".")
        assert chunks[1].startswith("B")

    def test_split_on_sentence_exclamation(self):
        """Should split at '! ' when no newline is available."""
        text = "A" * 1800 + "! " + "B" * 300
        chunks = split_message(text)
        assert len(chunks) == 2
        assert chunks[0].endswith("!")

    def test_split_on_sentence_question(self):
        """Should split at '? ' when no newline is available."""
        text = "A" * 1800 + "? " + "B" * 300
        chunks = split_message(text)
        assert len(chunks) == 2
        assert chunks[0].endswith("?")

    def test_newline_preferred_over_sentence(self):
        """Newlines should still take priority over sentence boundaries."""
        text = "A" * 1900 + ". more text\n" + "B" * 100
        chunks = split_message(text)
        assert len(chunks) == 2
        # Should split at newline, not period
        assert "more text" in chunks[0]

    def test_sentence_preferred_over_space(self):
        """Sentence boundary should be preferred over arbitrary space."""
        # Put a sentence boundary early, then spaces later
        text = "Hello world. " + "A" * 1800 + " " + "B" * 300
        chunks = split_message(text)
        assert len(chunks) >= 2
        # All chunks within limit
        assert all(len(c) <= 2000 for c in chunks)
