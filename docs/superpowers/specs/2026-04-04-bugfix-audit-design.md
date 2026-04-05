# Shannon Bugfix Audit — Design Spec

**Date:** 2026-04-04
**Scope:** Fix all 25 findings from the comprehensive codebase audit.
**Strategy:** Module-ordered batches — group fixes by file/subsystem for clean diffs.

---

## Batch 1: Config System (`config.py`)

Fixes: #2, #4, #8, #14, #15, #19, #21

### F2 — Add missing `enable_1m_context` to `_build_defaults()`

**Problem:** `_build_defaults()` uses `__new__` to skip `__post_init__`, but omits `enable_1m_context`. Accessing it raises `AttributeError`.

**Fix:** Add `llm.enable_1m_context = True` after line 208.

### F14 — Replace fragile `__new__` pattern with `_skip_validation` flag

**Problem:** Every new field added to `LLMConfig` or `MessagingConfig` that isn't manually set in `_build_defaults()` will be silently missing. This already caused F2 and will happen again.

**Fix:** Replace the `__new__` pattern. Instead, add a module-level `_SKIP_VALIDATION = False` flag. `_build_defaults()` sets it to `True`, constructs normally via `__init__` (which calls `__post_init__`), then resets. `__post_init__` methods check the flag and skip validation when set. This ensures all field defaults are applied via normal `__init__`, while still deferring validation until after YAML merge.

Concretely:
```python
_SKIP_VALIDATION = False

@dataclass
class LLMConfig:
    ...
    def __post_init__(self) -> None:
        if _SKIP_VALIDATION:
            return
        self.max_tokens = max(1, self.max_tokens)
        if not self.api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            raise ValueError(...)
```

`_build_defaults()` becomes:
```python
def _build_defaults() -> ShannonConfig:
    global _SKIP_VALIDATION
    _SKIP_VALIDATION = True
    try:
        config = ShannonConfig()
    finally:
        _SKIP_VALIDATION = False
    return config
```

This eliminates the `__new__` calls entirely. F2 is automatically fixed as a side-effect.

### F19 — Ensure sub-config `__post_init__` runs on no-config-file path

**Problem:** When no config.yaml exists, `_merge_dataclass(config, {})` only triggers `__post_init__` on the root, not nested sub-configs.

**Fix:** This is automatically fixed by F14. With the `_skip_validation` pattern, `_build_defaults()` creates a fully-initialized `ShannonConfig` via normal `__init__`. When `_merge_dataclass(config, {})` is called (empty overrides), it recurses into each sub-config and calls `__post_init__` — which now runs validation because `_SKIP_VALIDATION` is `False` again.

### F4 — Add type coercion in `_merge_dataclass` for security-critical fields

**Problem:** YAML `admin_ids: "alice"` (string) passes through as-is. Python `in` on a string does substring matching, enabling admin privilege escalation.

**Fix:** Add type coercion in `_merge_dataclass` before `setattr`. When the target field's current value is a `list` and the override is a scalar, wrap it: `value = [value]`. When the target is `bool` and override is `int`, coerce: `value = bool(value)`. When the target is `int`/`float` and override is a string, attempt conversion with a warning on failure.

```python
def _merge_dataclass(instance: Any, overrides: dict) -> None:
    for key, value in overrides.items():
        if not hasattr(instance, key):
            _log.warning("Unknown config key %r — ignored (typo?)", key)
            continue
        current = getattr(instance, key)
        if isinstance(value, dict) and hasattr(current, "__dataclass_fields__"):
            _merge_dataclass(current, value)
        else:
            # Type coercion for safety-critical mismatches
            if isinstance(current, list) and not isinstance(value, list):
                value = [value] if value is not None else []
            elif isinstance(current, bool) and not isinstance(value, bool):
                value = bool(value)
            elif isinstance(current, int) and not isinstance(value, int):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    _log.warning("Cannot convert %r to int for %s; skipping", value, key)
                    continue
            elif isinstance(current, float) and not isinstance(value, float):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    _log.warning("Cannot convert %r to float for %s; skipping", value, key)
                    continue
            setattr(instance, key, value)
    if hasattr(instance, "__post_init__"):
        instance.__post_init__()
```

**Note:** The `bool` check must come before `int` since `bool` is a subclass of `int` in Python. Check `isinstance(current, bool)` first.

### F21 — Warn on unknown config keys

**Problem:** Typos in config.yaml (e.g., `debuonce_delay`) are silently ignored.

**Fix:** Already included in the F4 implementation above — the `if not hasattr` branch now logs a warning instead of silently continuing.

### F15 — `_clamp` returns default instead of nearest boundary

**Problem:** `debounce_delay=-1` returns `3.0` (default) instead of `0` (lower bound). Surprising behavior.

**Fix:** Change `_clamp` to actually clamp:
```python
def _clamp(value: float, lo: float, hi: float, name: str) -> float:
    if lo <= value <= hi:
        return value
    clamped = max(lo, min(hi, value))
    _log.warning("%s=%.4g out of range [%.4g, %.4g]; clamping to %.4g.", name, value, lo, hi, clamped)
    return clamped
```

Update all call sites to remove the `default` parameter.

---

## Batch 2: Brain & Claude Client (`brain/brain.py`, `brain/claude.py`)

Fixes: #3, #6, #11, #16, #23

### F3 — Guard against empty assistant message in history

**Problem:** Tool-only LLM responses (no text) store `LLMMessage(role="assistant", content="")` in history. Replayed on next turn, this causes API 400.

**Fix:** In `_process_input`, after the tool loop, guard the history append:
```python
if combined_text:
    self._history.append(LLMMessage(role="user", content=...))
    self._history.append(LLMMessage(role="assistant", content=combined_text))
# else: tool-only turn — omit from history to avoid empty assistant message
```

If `combined_text` is empty, skip both the user and assistant history entries for this turn. The tool results were ephemeral; the next turn doesn't need to see this exchange.

### F6 — Prevent `_normalize_messages` from merging tool_use/tool_result blocks

**Problem:** Merging consecutive same-role messages can corrupt tool_use/tool_result pairing or produce empty `content: ""`.

**Fix:** In `_normalize_messages`, refuse to merge messages that contain `tool_use` or `tool_result` blocks:
```python
def _has_tool_blocks(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    return any(
        b.get("type") in ("tool_use", "tool_result")
        for b in content if isinstance(b, dict)
    )

# In the merge loop:
if prev["role"] == msg["role"]:
    if _has_tool_blocks(prev["content"]) or _has_tool_blocks(msg["content"]):
        merged.append(msg)  # don't merge — preserve tool block integrity
        continue
    # ... existing merge logic
```

### F11 — Clear history when `max_session_messages = 0`

**Problem:** History list grows unbounded when `max_session_messages = 0` (stateless mode).

**Fix:** After the history append block, add:
```python
if max_history > 0 and len(self._history) > max_history:
    self._history = self._history[-max_history:]
elif max_history == 0:
    self._history.clear()
```

### F16 — Replace `assert` with explicit check

**Problem:** `assert self._prompt_builder is not None` is optimized away with `python -O`.

**Fix:**
```python
if self._prompt_builder is None:
    raise RuntimeError("Brain.start() must be called before processing input")
```

### F23 — Same pattern: already covered by F16 (this was the only assert in brain.py)

No additional change needed.

---

## Batch 3: Tool Confirmation System (`brain/tool_dispatch.py`, `tools/*.py`, `computer/executor.py`)

Fixes: #1

### F1 — Implement bus-based confirmation gate with CLI stdin fallback

**Problem:** `require_confirmation` exists in config but is never checked. All tool execution is unguarded.

**Design:** Add a confirmation mechanism to `ToolDispatcher` that:
1. Checks `require_confirmation` on the relevant config before dispatching
2. Publishes a confirmation request event to the bus
3. A CLI confirmation handler (wired in `app.py`) prompts via stdin
4. If no handler responds (or the bus has no subscribers for the event), defaults to **deny**

**New event types** in `events.py`:
```python
@dataclass
class ToolConfirmationRequest:
    """Request user approval before executing a tool."""
    tool_name: str
    description: str  # human-readable summary of what the tool will do
    request_id: str

@dataclass
class ToolConfirmationResponse:
    """User's approval/denial of a tool execution."""
    request_id: str
    approved: bool
```

**Confirmation in ToolDispatcher:**

Add config references to `ToolDispatcher.__init__`:
```python
def __init__(self, ..., tools_config: ToolsConfig, bus: EventBus) -> None:
```

Before dispatching bash/computer/text_editor, check the config flag and await confirmation:
```python
async def dispatch(self, tool_call: LLMToolCall) -> str | dict:
    name = tool_call.name
    args = tool_call.arguments

    if name == "continue":
        return "ok"
    if name == "set_expression":
        return "ok"

    # Confirmation gate
    needs_confirm = self._needs_confirmation(name)
    if needs_confirm:
        approved = await self._request_confirmation(name, args)
        if not approved:
            return f"Tool '{name}' was denied by the user."

    # ... existing dispatch logic
```

`_needs_confirmation` checks the relevant config:
```python
def _needs_confirmation(self, name: str) -> bool:
    if name == "bash":
        return self._config.bash.require_confirmation
    if name == "str_replace_based_edit_tool":
        return self._config.text_editor.require_confirmation
    if name == "computer":
        return self._config.computer_use.require_confirmation
    return False
```

`_request_confirmation` publishes the event and waits:
```python
async def _request_confirmation(self, name: str, args: dict) -> bool:
    request_id = str(uuid.uuid4())
    description = self._describe_tool_call(name, args)
    event = ToolConfirmationRequest(
        tool_name=name, description=description, request_id=request_id
    )
    future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
    self._pending_confirmations[request_id] = future
    await self._bus.publish(event)
    try:
        return await asyncio.wait_for(future, timeout=120)
    except asyncio.TimeoutError:
        return False
    finally:
        self._pending_confirmations.pop(request_id, None)
```

`_describe_tool_call` produces a human-readable summary:
- bash: shows the command string
- text_editor: shows "command: X on path: Y"
- computer: shows "action: X at coordinate: Y"

**CLI confirmation handler** — a small function wired in `app.py` that subscribes to `ToolConfirmationRequest`:
```python
async def _cli_confirm_handler(event: ToolConfirmationRequest) -> None:
    loop = asyncio.get_running_loop()
    answer = await loop.run_in_executor(
        None, lambda: input(f"[{event.tool_name}] {event.description}\nAllow? [y/N]: ")
    )
    approved = answer.strip().lower() in ("y", "yes")
    await bus.publish(ToolConfirmationResponse(
        request_id=event.request_id, approved=approved
    ))
```

`ToolDispatcher` also subscribes to `ToolConfirmationResponse` and resolves the matching future.

**Wiring in `app.py`:**
- Pass `tools_config` and `bus` to `ToolDispatcher`
- Subscribe `_cli_confirm_handler` to `ToolConfirmationRequest`
- Subscribe dispatcher's response handler to `ToolConfirmationResponse`

---

## Batch 4: Memory & Text Editor Safety (`tools/memory_backend.py`, `tools/text_editor_executor.py`)

Fixes: #5

### F5 — Tighten memory containment check to `_memories_root`

**Problem:** Containment check uses `self._base` instead of `self._memories_root`. Symlink escape allows access to any file in `base_dir`.

**Fix:** Change line 55:
```python
# Before:
candidate.relative_to(self._base)
# After:
candidate.relative_to(self._memories_root)
```

One-line change. The text editor has no containment (by design — it's the LLM's general-purpose file editor, guarded by F1's confirmation system).

---

## Batch 5: Messaging System (`messaging/manager.py`, `messaging/providers/discord.py`)

Fixes: #7, #8, #9, #24, #25

### F8 — Split CancelledError handling: debounce vs publish phase

**Problem:** `CancelledError` during `bus.publish` silently drops a message that survived debounce.

**Fix:** Restructure `_debounced_publish` to only catch `CancelledError` during the sleep:
```python
async def _debounced_publish() -> None:
    typing_task: asyncio.Task | None = None
    try:
        provider = self._providers.get(platform)
        if self._config.debounce_delay > 0:
            if provider:
                try:
                    await provider.send_typing(channel_id)
                except Exception:
                    pass
            try:
                await asyncio.sleep(self._config.debounce_delay)
            except asyncio.CancelledError:
                return  # legitimately pre-empted by newer message

        if provider:
            typing_task = asyncio.create_task(_typing_loop(provider, channel_id))

        await self._bus.publish(event)
    finally:
        if typing_task is not None:
            typing_task.cancel()
        if self._pending.get(key) is task:
            del self._pending[key]
```

The key change: `CancelledError` is caught only around `asyncio.sleep`, not around `bus.publish`. If cancellation happens during publish, it propagates naturally (the event bus handler in brain is already under a lock, so this won't corrupt state).

### F9 — Remove dead `ChatReaction` with empty emoji

**Problem:** `ChatReaction(emoji="")` is published, producing a failed API call every time.

**Fix:** Remove the entire block (lines 134-138 of `manager.py`). This was an unfinished feature stub. The `reaction_probability` config field can stay (it's documented), but the handler should be a no-op until emoji selection is implemented.

```python
if not self._should_respond(...):
    return  # Remove the ChatReaction block entirely
```

### F7 — Guard against sending typing indicator for empty responses

**Problem:** Typing indicator fires even when `text` is empty, causing a "typing then nothing" flash.

**Fix:** In `_on_chat_response`, guard the typing indicator:
```python
async def _on_chat_response(self, event: ChatResponse) -> None:
    provider = self._providers.get(event.platform)
    if provider is None:
        return

    if event.text:
        try:
            await provider.send_typing(event.channel)
        except Exception:
            pass
        reply_to = event.reply_to if event.reply_to else None
        await provider.send_message(event.channel, event.text, reply_to=reply_to)

    if event.reactions and event.reply_to:
        for emoji in event.reactions:
            await provider.add_reaction(event.channel, event.reply_to, emoji)
```

### F24 — Reactions on continue follow-ups dropped silently

**Problem:** Only the first message in a continue chain has `reply_to`, so reactions on follow-ups are dropped.

**Fix:** This is a known limitation documented in the log message. The proper fix (returning message IDs from `send_message` and using them as reaction targets) requires changing the `MessagingProvider` interface. For now, add a comment documenting the limitation. This is low-severity and can be addressed in a future messaging refactor.

No code change — just acknowledge in a comment.

### F25 — Sentence-boundary split margin

**Problem:** `margin = DISCORD_MAX_LENGTH - 100` ignores valid sentence boundaries between positions 1900-2000.

**Fix:** Change to `margin = DISCORD_MAX_LENGTH` — let the sentence boundary search use the full range. The 100-char margin was overly conservative:
```python
best_sentence = -1
for punc in (". ", "! ", "? "):
    idx = remaining.rfind(punc, 0, DISCORD_MAX_LENGTH)
    if idx > best_sentence:
        best_sentence = idx + 1
```

---

## Batch 6: I/O, Vision, Autonomy

Fixes: #7 (webcam), #10, #12, #13, #15 (speak), #16 (webcam release), #17, #18, #20, #22

### F7-webcam — Offload webcam capture to executor

**Problem:** `WebcamCapture.capture()` blocks the event loop with `cap.read()`.

**Fix:** Same pattern as `ScreenCapture` — move the blocking work into a sync method and call via `run_in_executor`:
```python
async def capture(self) -> bytes:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, self._capture_sync)

def _capture_sync(self) -> bytes:
    # existing blocking code moves here
```

### F16-webcam — Release webcam on shutdown

**Problem:** `WebcamCapture.release()` exists but is never called.

**Fix:** Add an optional `async def close(self)` method to the `VisionProvider` base class (default no-op). Implement it in `WebcamCapture` to call `release()`. Call it from `app.py` shutdown:
```python
# In app.py shutdown:
for provider in vision_providers:
    if hasattr(provider, 'close'):
        await provider.close()
```

### F17 — Create `mss` instance per-capture instead of sharing

**Problem:** Single `mss.mss()` instance is thread-unsafe when shared across executor calls.

**Fix:** In `ScreenCapture._capture_sync`, create a fresh `mss.mss()` context manager per call instead of caching in `self._mss`:
```python
def _capture_sync(self) -> bytes:
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        screenshot = sct.grab(monitor)
        # ... rest of capture
```

Remove the `_get_mss()` lazy initialization method and `self._mss` field.

### F10-piper — Offload `stream_synthesize` to executor

**Problem:** `synthesize_stream_raw()` is a blocking generator run on the event loop.

**Fix:** Same executor pattern. The streaming nature makes this slightly different — collect chunks in a sync wrapper:
```python
async def stream_synthesize(self, text):
    loop = asyncio.get_running_loop()
    chunks = await loop.run_in_executor(None, self._stream_sync, text)
    for chunk in chunks:
        yield chunk

def _stream_sync(self, text):
    return list(self._voice.synthesize_stream_raw(text))
```

This loses the streaming benefit (all chunks are collected before any are yielded), but it unblocks the event loop. True async streaming would require a more complex producer/consumer pattern — out of scope for this fix.

### F15-speak — Add duration wait between start/stop speaking

**Problem:** `start_speaking()` and `stop_speaking()` are called back-to-back with no audio duration.

**Fix:**
```python
if self._vtuber is not None:
    await self._vtuber.start_speaking(phonemes=phonemes)

if duration > 0:
    await asyncio.sleep(duration)

if self._vtuber is not None:
    await self._vtuber.stop_speaking()
```

### F12 — Add basic VTube Studio error handling

**Problem:** No auth failure detection, no reconnection, websocket errors propagate.

**Fix:** Three targeted changes:

1. Check auth response:
```python
resp = await self._recv()
if not resp.get("data", {}).get("authenticated"):
    logger.warning("VTube Studio authentication failed")
    self._ws = None
    return
```

2. Wrap `_send()` in try/except for disconnection:
```python
async def _send(self, data):
    if self._ws is None:
        return
    try:
        await self._ws.send(json.dumps(data))
    except websockets.exceptions.ConnectionClosed:
        logger.warning("VTube Studio disconnected")
        self._ws = None
```

3. No reconnection logic (out of scope) — just fail gracefully with warnings.

### F13 — Autonomy cooldown timing (no change needed)

**Problem (as reported):** Cooldown is set when trigger is published, not when brain processes it.

**Re-analysis:** `await self._bus.publish(...)` blocks until the brain handler returns (including lock wait time). `_last_trigger_time = now` is set *before* the publish, but the `_evaluate` loop is sequential — it can't fire another trigger until the current `publish` await returns. So triggers cannot queue, and cooldown effectively starts from when the brain finishes processing. **No code change needed.**

### F18 — Fix shutdown order

**Problem:** `output_manager.stop()` runs before `messaging_manager.stop()`, causing responses during shutdown to be dropped.

**Fix:** In `app.py` shutdown, move `messaging_manager.stop()` before `output_manager.stop()`:
```python
finally:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await messaging_manager.stop()  # Stop accepting messages first
    autonomy_loop.stop()
    vision_manager.stop()
    await bash_executor.close()
    output_manager.stop()            # Then stop output
    ...
```

### F20 — Vision interval drift

**Problem:** Capture time is not subtracted from sleep interval.

**Fix:** Track elapsed time:
```python
async def run(self):
    while self._running:
        start = asyncio.get_event_loop().time()
        # ... capture all providers ...
        elapsed = asyncio.get_event_loop().time() - start
        sleep_time = max(0, self._interval - elapsed)
        await asyncio.sleep(sleep_time)
```

### F22 — Frozen dataclass with mutable fields

**Problem:** `GenerationRequest` is `frozen=True` but contains `list` and `dict` fields.

**Fix:** No code change. This is a documentation/style issue. The `frozen=True` prevents field reassignment, which is the intent. Adding `tuple` conversion would be overly defensive for internal-only types. Add a comment:
```python
@dataclass(frozen=True)
class GenerationRequest:
    """... Frozen prevents field reassignment; contained collections are
    still mutable by convention but should not be modified after creation."""
```

---

## Batch 7: Tests

Update tests to cover the new behaviors:

1. **Config tests:** Test that `_build_defaults()` + `load_config()` produces a complete config with all fields. Test type coercion (string `admin_ids` wrapped in list). Test unknown key warning.
2. **Brain tests:** Test tool-only response (no text) doesn't produce empty assistant in history. Test `_normalize_messages` refuses to merge tool_use blocks.
3. **Tool dispatch tests:** Test confirmation gate — mock the bus, verify `ToolConfirmationRequest` is published, verify denied tool returns error string.
4. **Memory tests:** Test that `_resolve` checks against `_memories_root` not `_base`.
5. **Messaging tests:** Test debounce cancellation during sleep vs during publish. Test empty-emoji reaction block is removed.
6. **Update existing `test_brain_pause_turn` test** (already done in prior session).

---

## Out of Scope

These were considered and deliberately excluded:

- **Full VTube Studio reconnection logic** — would require a connection manager with exponential backoff; the graceful-failure fix in F12 is sufficient for now.
- **Async streaming TTS** — the executor-offload fix in F10-piper loses streaming but unblocks the event loop. True async streaming needs a producer/consumer channel, which is a larger refactor.
- **Returning message IDs from `send_message`** for F24 (continue reaction targeting) — requires changing the `MessagingProvider` interface across all implementations.
- **Path restriction for text editor** — the tool is intentionally broad-access; the confirmation gate (F1) is the security boundary.
