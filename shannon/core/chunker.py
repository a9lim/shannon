"""Intelligent message chunking for platform-specific limits."""

from __future__ import annotations

import re

from shannon.config import ChunkerConfig


# Regex for fenced code blocks
_CODE_BLOCK_RE = re.compile(r"(```[\s\S]*?```)", re.MULTILINE)
_PARAGRAPH_RE = re.compile(r"\n{2,}")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_RE = re.compile(r"(?<=[,;:])\s+")


def chunk_message(
    text: str,
    limit: int = 1900,
    config: ChunkerConfig | None = None,
) -> list[str]:
    """Split text into chunks respecting platform limits and structure."""
    if config:
        min_chunk = config.min_chunk_size
    else:
        min_chunk = 100

    if len(text) <= limit:
        return [text]

    # Separate code blocks from prose
    segments = _split_preserving_code(text)

    chunks: list[str] = []
    current = ""

    for segment in segments:
        is_code = segment.startswith("```")

        # If segment fits in current chunk, append
        if len(current) + len(segment) + 1 <= limit:
            current = f"{current}\n{segment}".strip() if current else segment
            continue

        # Flush current chunk if non-empty
        if current:
            chunks.append(current)
            current = ""

        # If segment itself fits in one chunk
        if len(segment) <= limit:
            current = segment
            continue

        # Segment too large — split it
        if is_code:
            # Split code block into multiple fenced blocks
            sub_chunks = _split_code_block(segment, limit)
            chunks.extend(sub_chunks[:-1])
            current = sub_chunks[-1] if sub_chunks else ""
        else:
            sub_chunks = _split_prose(segment, limit)
            chunks.extend(sub_chunks[:-1])
            current = sub_chunks[-1] if sub_chunks else ""

    if current:
        chunks.append(current)

    # Merge very short chunks
    chunks = _merge_short_chunks(chunks, limit, min_chunk)
    return chunks


def _split_preserving_code(text: str) -> list[str]:
    """Split text into alternating prose / code-block segments."""
    parts = _CODE_BLOCK_RE.split(text)
    return [p for p in parts if p.strip()]


def _split_prose(text: str, limit: int) -> list[str]:
    """Split prose by paragraph -> sentence -> clause -> word boundaries."""
    # Try paragraphs first
    parts = _PARAGRAPH_RE.split(text)
    if all(len(p) <= limit for p in parts) and len(parts) > 1:
        return _recombine(parts, limit, "\n\n")

    # Try sentences
    chunks: list[str] = []
    for part in parts:
        if len(part) <= limit:
            chunks.append(part)
        else:
            sentences = _SENTENCE_RE.split(part)
            if len(sentences) > 1:
                chunks.extend(_recombine(sentences, limit, " "))
            else:
                # Fall back to clause / word
                clauses = _CLAUSE_RE.split(part)
                if len(clauses) > 1:
                    chunks.extend(_recombine(clauses, limit, " "))
                else:
                    chunks.extend(_split_by_words(part, limit))
    return chunks


def _split_code_block(block: str, limit: int) -> list[str]:
    """Split a code block across multiple fenced blocks."""
    lines = block.split("\n")
    # First line has the opening ``` with optional language
    opener = lines[0] if lines else "```"
    closer = "```"
    inner_lines = lines[1:-1] if len(lines) >= 2 else lines[1:]

    overhead = len(opener) + len(closer) + 2  # newlines
    max_inner = limit - overhead

    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in inner_lines:
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > max_inner and current_lines:
            chunks.append(f"{opener}\n" + "\n".join(current_lines) + f"\n{closer}")
            current_lines = []
            current_len = 0
        current_lines.append(line)
        current_len += line_len

    if current_lines:
        chunks.append(f"{opener}\n" + "\n".join(current_lines) + f"\n{closer}")

    return chunks if chunks else [block]


def _recombine(parts: list[str], limit: int, separator: str) -> list[str]:
    """Recombine split parts into chunks within the limit."""
    chunks: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}{separator}{part}" if current else part
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(part) <= limit:
                current = part
            else:
                # Part itself too big, split by words
                sub = _split_by_words(part, limit)
                chunks.extend(sub[:-1])
                current = sub[-1] if sub else ""
    if current:
        chunks.append(current)
    return chunks


def _split_by_words(text: str, limit: int) -> list[str]:
    """Last-resort split by word boundaries."""
    words = text.split()
    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = word if len(word) <= limit else word[:limit]
    if current:
        chunks.append(current)
    return chunks


def _merge_short_chunks(
    chunks: list[str], limit: int, min_size: int
) -> list[str]:
    """Merge consecutive short chunks."""
    if not chunks:
        return chunks
    merged: list[str] = [chunks[0]]
    for chunk in chunks[1:]:
        if len(merged[-1]) < min_size and len(merged[-1]) + len(chunk) + 1 <= limit:
            merged[-1] = f"{merged[-1]}\n{chunk}"
        else:
            merged.append(chunk)
    return merged
