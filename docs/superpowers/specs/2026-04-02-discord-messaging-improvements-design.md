# Discord & Messaging Improvements Design

Cross-audit of Faithful's Discord bot implementation identified 16 actionable improvements for Shannon's messaging and Anthropic API layers. This spec covers all of them.

## Architecture Decision

Split responsibilities between two layers:

- **MessagingManager** (platform-agnostic): behavioral logic -- debouncing, conversation continuity, random replies/reactions, response timing
- **DiscordProvider** (platform-specific): Discord API mechanics -- message splitting, typing indicators, reaction API, attachment download, error handling

No new classes. Enrich the existing `MessagingManager` and `DiscordProvider`.

## 1. MessagingManager Behavioral Logic

### New State

```python
_pending: dict[str, asyncio.Task]    # per-channel debounce tasks, keyed "platform:channel"
_last_response: dict[str, float]     # per-channel timestamp of last bot response
```

### Incoming Message Flow

1. Provider callback delivers message to manager.
2. `_should_respond()` evaluates:
   - Is it a direct mention? -> respond
   - Is it a reply to the bot? -> respond
   - Is there an active conversation (bot responded in this channel within `conversation_expiry` seconds)? -> respond
   - Random roll against `reply_probability`? -> respond
   - Otherwise -> roll `reaction_probability`, if hit publish `ChatReaction` event
3. If responding: cancel any existing pending task for this channel, create a new debounce task that waits `debounce_delay` seconds, then publishes `ChatMessage` to the bus.
4. On `ChatResponse` from brain: update `_last_response[channel_key]` timestamp.

### Outgoing Response Flow

- Route `ChatResponse` to provider as before.
- Also route `ChatReaction` events to provider's `add_reaction()`.

## 2. DiscordProvider Enhancements

### Message Sending

- `send_message()` splits text at 2000-char boundaries: split on newlines first, then word boundaries, then hard cut.
- New `send_typing(channel: str)` method wraps `channel.typing()`.
- New `add_reaction(channel: str, message_id: str, emoji: str)` method wraps `message.add_reaction()` with `DiscordException` catch (best-effort, silent failure).

### Message Receiving

- Filter all bot authors (`message.author.bot`), not just self.
- Download image attachments, read text file attachments inline, annotate other file types.
- Detect reply-to-bot and mention status.

### Extended Callback Signature

```python
callback(
    text: str,
    author: str,
    channel_id: str,
    message_id: str,
    attachments: list[dict],   # [{"filename": ..., "content_type": ..., "data": bytes}]
    is_reply_to_bot: bool,
    is_mention: bool,
)
```

### Error Handling

- `send_message()` catches `DiscordException`, logs it, adds warning reaction to original message if `reply_to` available.
- Attachment download failures logged and skipped (best-effort).

## 3. Event Bus Changes

### ChatMessage -- new fields

```python
@dataclass
class ChatMessage:
    text: str
    author: str
    platform: str
    channel: str
    message_id: str = ""
    attachments: list[dict] = field(default_factory=list)
    is_reply_to_bot: bool = False
    is_mention: bool = False
```

Manager uses `is_reply_to_bot` and `is_mention` for `_should_respond()`. These don't reach the brain -- the manager decides whether to publish.

### ChatResponse -- new field

```python
@dataclass
class ChatResponse:
    text: str
    platform: str
    channel: str
    reply_to: str = ""
    reactions: list[str] = field(default_factory=list)
```

### New event: ChatReaction

```python
@dataclass
class ChatReaction:
    emoji: str
    platform: str
    channel: str
    message_id: str
```

## 4. Brain Adaptations

### Attachment Handling

In `Brain._on_chat_message()`:
- Extract image bytes from `event.attachments` (where `content_type` starts with `image/`), pass as `images` to `_process_input()`. Already supported -- `_process_input` accepts `images: list[bytes]`.
- Text file attachments (`content_type` starts with `text/`): decode and append to message text as `\n[File: filename]\ncontent`.
- Other files: append `\n[Attached file: filename]`.

### Reaction Extraction

New utility `shannon/brain/reactions.py`:

```python
_REACTION_PATTERN = re.compile(r"\[react:\s*([^\]]+)\]")

def extract_reactions(text: str) -> tuple[str, list[str]]:
    reactions = _REACTION_PATTERN.findall(text)
    clean = _REACTION_PATTERN.sub("", text).strip()
    return clean, [r.strip() for r in reactions if r.strip()]
```

Used in `Brain._on_chat_message()`: after `_process_input()` returns response texts, run `extract_reactions()` on each, populate `ChatResponse.reactions` with extracted emoji, send cleaned text.

## 5. Anthropic API Improvements

### Message Role Normalization

Add `_normalize_messages()` in `ClaudeClient._build_messages()` as a post-processing pass. Merges consecutive same-role messages by concatenating text content. Defensive against edge cases where the brain produces malformed alternation.

### Server-Side Tool Rate Limits

In `ToolRegistry.build()`, add `max_uses: 3` to `web_search` and `web_fetch` tool definitions. Prevents runaway API costs.

## 6. Config Changes

### New MessagingConfig Fields

```python
@dataclass
class MessagingConfig:
    type: str = "discord"
    enabled: bool = False
    token: str = ""
    debounce_delay: float = 3.0
    reply_probability: float = 0.0      # off by default
    reaction_probability: float = 0.0   # off by default
    conversation_expiry: float = 300.0
    max_context_messages: int = 20
```

### Config Validation

Add `_clamp(value, lo, hi, name, default)` helper that logs a warning and returns default when out of range.

**MessagingConfig `__post_init__`:**
- `debounce_delay`: [0, 60]
- `reply_probability`: [0, 1]
- `reaction_probability`: [0, 1]
- `conversation_expiry`: [0, 3600]
- `max_context_messages`: >= 0

**LLMConfig `__post_init__`:**
- `max_tokens`: >= 1
- Warn if `api_key` empty and `ANTHROPIC_API_KEY` env var unset

## 7. MessagingProvider Base Class

Extend `MessagingProvider` abstract interface:

```python
async def send_typing(self, channel: str) -> None: ...
async def add_reaction(self, channel: str, message_id: str, emoji: str) -> None: ...
```

Extended callback signature with attachments, is_reply_to_bot, is_mention.

## 8. Files Changed

| File | Changes |
|---|---|
| `shannon/config.py` | 5 new `MessagingConfig` fields, `_clamp()` helper, `__post_init__` on `MessagingConfig` and `LLMConfig` |
| `shannon/events.py` | New fields on `ChatMessage` and `ChatResponse`, new `ChatReaction` event |
| `shannon/messaging/manager.py` | Per-channel state, debouncing, `_should_respond()`, conversation continuity, random reply/reaction, typing trigger, reaction routing |
| `shannon/messaging/providers/discord.py` | Message splitting, typing indicators, reaction API, attachment download, bot-message filtering, error handling |
| `shannon/messaging/providers/base.py` | Extended callback signature, `send_typing()`, `add_reaction()` abstract methods |
| `shannon/brain/reactions.py` | New file -- `extract_reactions()` |
| `shannon/brain/brain.py` | Use `extract_reactions()` in `_on_chat_message()`, pass attachments as images, text file content appended to message |
| `shannon/brain/claude.py` | `_normalize_messages()` post-pass |
| `shannon/brain/tool_registry.py` | `max_uses: 3` on web_search, web_fetch |

## 9. Findings Not Implemented

| Finding | Reason |
|---|---|
| #11 pause_turn handling | Already exists in `brain.py:200-204` |
| #15 Discord history re-read | Shannon's event bus maintains its own history; re-reading would create duplicate state |
| #16 Spontaneous scheduler | Shannon's autonomy loop serves this purpose |
| #17 Custom emoji awareness | Would require passing guild state through the event bus; low value relative to complexity |
| #19 Memory path traversal | Shannon uses Anthropic's hosted memory tool, no local executor |
