# Bugfix Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 25 findings from the Shannon codebase audit, organized into 7 module-ordered batches.

**Architecture:** Each batch touches one subsystem. Tests are written alongside each fix (TDD where practical). Batches are independent and can be committed separately.

**Tech Stack:** Python 3.12+, pytest, pytest-asyncio, dataclasses, asyncio

**Spec:** `docs/superpowers/specs/2026-04-04-bugfix-audit-design.md`

---

### Task 1: Config — Replace `_build_defaults` `__new__` pattern (F2, F14, F19)

**Files:**
- Modify: `shannon/config.py:15-244`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing test — `_build_defaults` produces complete LLMConfig**

Add to `tests/test_config.py`:

```python
def test_build_defaults_has_all_llm_fields():
    """_build_defaults must produce an LLMConfig with every declared field."""
    from shannon.config import _build_defaults
    cfg = _build_defaults()
    # Every field in LLMConfig.__dataclass_fields__ must exist on the instance
    from shannon.config import LLMConfig
    for field_name in LLMConfig.__dataclass_fields__:
        assert hasattr(cfg.llm, field_name), f"Missing field: llm.{field_name}"
    # Spot-check the field that was previously missing
    assert cfg.llm.enable_1m_context is True


def test_build_defaults_has_all_messaging_fields():
    """_build_defaults must produce a MessagingConfig with every declared field."""
    from shannon.config import _build_defaults, MessagingConfig
    cfg = _build_defaults()
    for field_name in MessagingConfig.__dataclass_fields__:
        assert hasattr(cfg.messaging, field_name), f"Missing field: messaging.{field_name}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_config.py::test_build_defaults_has_all_llm_fields -v`
Expected: FAIL with `AttributeError: 'LLMConfig' object has no attribute 'enable_1m_context'`

- [ ] **Step 3: Implement `_SKIP_VALIDATION` pattern**

In `shannon/config.py`, add a module-level flag after the imports:

```python
_SKIP_VALIDATION = False
```

Add `if _SKIP_VALIDATION: return` as the first line in every `__post_init__` method: `LLMConfig.__post_init__`, `VisionConfig.__post_init__`, `MessagingConfig.__post_init__`, `BashConfig.__post_init__`, `AutonomyConfig.__post_init__`, `MemoryConfig.__post_init__`.

Example for `LLMConfig`:
```python
def __post_init__(self) -> None:
    if _SKIP_VALIDATION:
        return
    self.max_tokens = max(1, self.max_tokens)
    if not self.api_key and not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError(
            "API key required: set llm.api_key in config.yaml or ANTHROPIC_API_KEY env var"
        )
```

Replace `_build_defaults()` entirely:

```python
def _build_defaults() -> ShannonConfig:
    """Build ShannonConfig with defaults, skipping __post_init__ validation."""
    global _SKIP_VALIDATION
    _SKIP_VALIDATION = True
    try:
        config = ShannonConfig()
    finally:
        _SKIP_VALIDATION = False
    return config
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/config.py tests/test_config.py
git commit -m "fix: replace fragile __new__ pattern with _SKIP_VALIDATION in config (F2, F14, F19)"
```

---

### Task 2: Config — Type coercion and unknown key warnings (F4, F21)

**Files:**
- Modify: `shannon/config.py:185-197`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_config.py`:

```python
def test_merge_dataclass_coerces_string_to_list(tmp_path):
    """A scalar YAML value for a list field should be wrapped in a list."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("messaging:\n  admin_ids: 'alice'\n")
    cfg = load_config(str(config_file))
    assert isinstance(cfg.messaging.admin_ids, list)
    assert cfg.messaging.admin_ids == ["alice"]


def test_merge_dataclass_warns_on_unknown_key(tmp_path, caplog):
    """Unknown config keys should log a warning, not be silently ignored."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("messaging:\n  typo_field: 42\n")
    with caplog.at_level(logging.WARNING):
        load_config(str(config_file))
    assert any("typo_field" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_config.py::test_merge_dataclass_coerces_string_to_list tests/test_config.py::test_merge_dataclass_warns_on_unknown_key -v`
Expected: FAIL — `admin_ids` is a string, no warning logged

- [ ] **Step 3: Implement type coercion in `_merge_dataclass`**

Replace `_merge_dataclass` in `shannon/config.py`:

```python
def _merge_dataclass(instance: Any, overrides: dict) -> None:
    """Recursively merge a dict of overrides into a dataclass instance."""
    for key, value in overrides.items():
        if not hasattr(instance, key):
            _log.warning("Unknown config key %r — ignored (typo?)", key)
            continue
        current = getattr(instance, key)
        if isinstance(value, dict) and hasattr(current, "__dataclass_fields__"):
            _merge_dataclass(current, value)
        else:
            # Type coercion: bool before int (bool is subclass of int)
            if isinstance(current, list) and not isinstance(value, list):
                value = [value] if value is not None else []
            elif isinstance(current, bool) and not isinstance(value, bool):
                value = bool(value)
            elif isinstance(current, int) and not isinstance(value, (int, bool)):
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    _log.warning("Cannot convert %r to int for %s; skipping", value, key)
                    continue
            elif isinstance(current, float) and not isinstance(value, (float, int)):
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    _log.warning("Cannot convert %r to float for %s; skipping", value, key)
                    continue
            setattr(instance, key, value)
    # Re-run validation after merging overrides
    if hasattr(instance, "__post_init__"):
        instance.__post_init__()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/config.py tests/test_config.py
git commit -m "fix: add type coercion and unknown-key warnings to config merge (F4, F21)"
```

---

### Task 3: Config — Fix `_clamp` to return clamped value (F15)

**Files:**
- Modify: `shannon/config.py:15-20` and all `_clamp` call sites
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_config.py`:

```python
def test_clamp_returns_boundary_not_default():
    """_clamp should return the nearest boundary, not a hardcoded default."""
    from shannon.config import _clamp
    # Value below lower bound should clamp to lower bound
    assert _clamp(-1.0, 0, 60, "test") == 0.0
    # Value above upper bound should clamp to upper bound
    assert _clamp(100.0, 0, 60, "test") == 60.0
    # Value in range should pass through
    assert _clamp(5.0, 0, 60, "test") == 5.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config.py::test_clamp_returns_boundary_not_default -v`
Expected: FAIL — `_clamp` signature mismatch (takes 5 args, test passes 4)

- [ ] **Step 3: Implement fix**

Replace `_clamp` in `shannon/config.py`:

```python
def _clamp(value: float, lo: float, hi: float, name: str) -> float:
    """Clamp a value to [lo, hi], logging a warning if out of range."""
    if lo <= value <= hi:
        return value
    clamped = max(lo, min(hi, value))
    _log.warning("%s=%.4g out of range [%.4g, %.4g]; clamping to %.4g.", name, value, lo, hi, clamped)
    return clamped
```

Update all call sites to remove the `default` parameter:

```python
# In MessagingConfig.__post_init__:
self.debounce_delay = _clamp(self.debounce_delay, 0, 60, "debounce_delay")
self.reply_probability = _clamp(self.reply_probability, 0, 1, "reply_probability")
self.reaction_probability = _clamp(self.reaction_probability, 0, 1, "reaction_probability")
self.conversation_expiry = _clamp(self.conversation_expiry, 0, 3600, "conversation_expiry")
```

- [ ] **Step 4: Run full config tests**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/config.py tests/test_config.py
git commit -m "fix: _clamp returns nearest boundary instead of default (F15)"
```

---

### Task 4: Brain — Guard empty assistant in history + unbounded history (F3, F11, F16)

**Files:**
- Modify: `shannon/brain/brain.py:182-397`
- Test: `tests/test_brain.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_brain.py`:

```python
class FakeClaudeToolOnly:
    """Returns only tool calls (no text) on the first call, then text on the second."""
    def __init__(self):
        self.call_count = 0
        self.messages_per_call = []

    async def generate(self, messages, tools=None, betas=None):
        self.call_count += 1
        self.messages_per_call.append(list(messages))
        if self.call_count == 1:
            return LLMResponse(
                text="",
                tool_calls=[LLMToolCall(id="tc1", name="bash", arguments={"command": "ls"})],
                stop_reason="end_turn",
            )
        return LLMResponse(text="done", tool_calls=[], stop_reason="end_turn")


@pytest.mark.asyncio
async def test_brain_tool_only_response_no_empty_history():
    """When the LLM responds with only tool calls and no text, history must not contain an empty assistant message."""
    fake_claude = FakeClaudeToolOnly()
    bus, brain = _make_brain(fake_claude=fake_claude)
    await brain.start()

    await bus.publish(UserInput(text="run ls", source="text"))

    # History should not contain an empty assistant message
    for msg in brain._history:
        if msg.role == "assistant":
            assert msg.content != "", "Empty assistant message found in history"


@pytest.mark.asyncio
async def test_brain_history_cleared_when_max_zero():
    """When max_session_messages=0, history should not accumulate."""
    bus, brain = _make_brain()
    brain._config.memory.max_session_messages = 0
    await brain.start()

    await bus.publish(UserInput(text="Hello", source="text"))
    await bus.publish(UserInput(text="World", source="text"))

    assert len(brain._history) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_brain.py::test_brain_tool_only_response_no_empty_history tests/test_brain.py::test_brain_history_cleared_when_max_zero -v`
Expected: FAIL — empty assistant message in history; history length > 0

- [ ] **Step 3: Implement fixes in `brain.py`**

Replace the `assert` at line 188:

```python
if self._prompt_builder is None:
    raise RuntimeError("Brain.start() must be called before processing input")
```

Replace the history persistence block (lines 382-395):

```python
            # ---- Persist to history ----
            # Store text-only copies in history (images are one-time context)
            combined_text = "\n\n".join(all_responses)
            if combined_text:
                self._history.append(LLMMessage(
                    role="user",
                    content=user_msg.content if isinstance(user_msg.content, str) else str(user_msg.content),
                ))
                self._history.append(LLMMessage(
                    role="assistant",
                    content=combined_text,
                ))
            # Trim history or clear for stateless mode
            if max_history > 0 and len(self._history) > max_history:
                self._history = self._history[-max_history:]
            elif max_history == 0:
                self._history.clear()
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_brain.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/brain/brain.py tests/test_brain.py
git commit -m "fix: guard empty assistant history, clear stateless history, replace assert (F3, F11, F16)"
```

---

### Task 5: Claude Client — Prevent merging tool blocks in `_normalize_messages` (F6)

**Files:**
- Modify: `shannon/brain/claude.py:124-148`
- Test: `tests/test_claude_client.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_claude_client.py`:

```python
def test_normalize_does_not_merge_tool_use_messages():
    """Consecutive assistant messages containing tool_use blocks must not be merged."""
    client = make_client()
    messages = [
        {"role": "assistant", "content": [
            {"type": "text", "text": "calling tool"},
            {"type": "tool_use", "id": "tu1", "name": "bash", "input": {}},
        ]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "calling another tool"},
            {"type": "tool_use", "id": "tu2", "name": "bash", "input": {}},
        ]},
    ]
    result = client._normalize_messages(messages)
    # Should remain as two separate messages, not merged
    assert len(result) == 2
    assert result[0]["content"][1]["id"] == "tu1"
    assert result[1]["content"][1]["id"] == "tu2"


def test_normalize_does_not_merge_tool_result_messages():
    """Consecutive user messages containing tool_result blocks must not be merged."""
    client = make_client()
    messages = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu1", "content": "ok"},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu2", "content": "ok"},
        ]},
    ]
    result = client._normalize_messages(messages)
    assert len(result) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_claude_client.py::test_normalize_does_not_merge_tool_use_messages tests/test_claude_client.py::test_normalize_does_not_merge_tool_result_messages -v`
Expected: FAIL — messages get merged (len == 1)

- [ ] **Step 3: Implement fix**

In `shannon/brain/claude.py`, replace `_normalize_messages`:

```python
@staticmethod
def _normalize_messages(api_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive same-role messages to ensure strict alternation.

    Messages containing tool_use or tool_result blocks are never merged,
    to preserve the required tool_use → tool_result pairing.
    """
    if not api_messages:
        return api_messages

    def _to_blocks(content: Any) -> list[dict[str, Any]]:
        if isinstance(content, list):
            return content
        if isinstance(content, str) and content:
            return [{"type": "text", "text": content}]
        return []

    def _has_tool_blocks(content: Any) -> bool:
        if not isinstance(content, list):
            return False
        return any(
            isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result")
            for b in content
        )

    merged: list[dict[str, Any]] = [api_messages[0]]
    for msg in api_messages[1:]:
        prev = merged[-1]
        if prev["role"] == msg["role"]:
            # Never merge messages with tool blocks
            if _has_tool_blocks(prev["content"]) or _has_tool_blocks(msg["content"]):
                merged.append(msg)
                continue
            prev_blocks = _to_blocks(prev["content"])
            new_blocks = _to_blocks(msg["content"])
            combined = prev_blocks + new_blocks
            merged[-1] = {"role": msg["role"], "content": combined if combined else ""}
        else:
            merged.append(msg)

    return merged
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_claude_client.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/brain/claude.py tests/test_claude_client.py
git commit -m "fix: prevent _normalize_messages from merging tool_use/tool_result blocks (F6)"
```

---

### Task 6: Tool Confirmation System (F1)

**Files:**
- Modify: `shannon/events.py`
- Modify: `shannon/brain/tool_dispatch.py`
- Modify: `shannon/app.py:96-104`
- Test: `tests/test_tool_dispatch.py`

- [ ] **Step 1: Write failing test — confirmation gate denies when no handler responds**

Add to `tests/test_tool_dispatch.py`:

```python
from shannon.bus import EventBus
from shannon.config import ToolsConfig


async def test_dispatch_bash_denied_when_confirmation_required(monkeypatch):
    """When require_confirmation=True and no handler approves, dispatch returns denial."""
    import shannon.brain.tool_dispatch as td
    monkeypatch.setattr(td, "_CONFIRMATION_TIMEOUT", 0.1)  # fast timeout for tests

    bus = EventBus()
    config = ToolsConfig()  # defaults: require_confirmation=True for all
    dispatcher = ToolDispatcher(
        bash_executor=AsyncMock(execute=AsyncMock(return_value="output")),
        tools_config=config,
        bus=bus,
    )
    # No ToolConfirmationResponse subscriber — should timeout and deny
    result = await dispatcher.dispatch(_make_call("bash", {"command": "ls"}))
    assert "denied" in result.lower()


async def test_dispatch_bash_allowed_when_confirmation_false():
    """When require_confirmation=False, dispatch executes without confirmation."""
    bus = EventBus()
    config = ToolsConfig()
    config.bash.require_confirmation = False
    bash = AsyncMock(execute=AsyncMock(return_value="output"))
    dispatcher = ToolDispatcher(
        bash_executor=bash,
        tools_config=config,
        bus=bus,
    )
    result = await dispatcher.dispatch(_make_call("bash", {"command": "ls"}))
    assert result == "output"
    bash.execute.assert_called_once()


async def test_dispatch_bash_approved_via_bus():
    """When a handler approves via ToolConfirmationResponse, dispatch proceeds."""
    from shannon.events import ToolConfirmationRequest, ToolConfirmationResponse

    bus = EventBus()
    config = ToolsConfig()
    bash = AsyncMock(execute=AsyncMock(return_value="output"))
    dispatcher = ToolDispatcher(
        bash_executor=bash,
        tools_config=config,
        bus=bus,
    )

    # Auto-approve handler
    async def auto_approve(event: ToolConfirmationRequest) -> None:
        await bus.publish(ToolConfirmationResponse(
            request_id=event.request_id, approved=True,
        ))

    bus.subscribe(ToolConfirmationRequest, auto_approve)

    result = await dispatcher.dispatch(_make_call("bash", {"command": "ls"}))
    assert result == "output"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_tool_dispatch.py::test_dispatch_bash_denied_when_confirmation_required -v`
Expected: FAIL — `ToolDispatcher.__init__` doesn't accept `tools_config` or `bus`

- [ ] **Step 3: Add event types to `events.py`**

Add at the end of `shannon/events.py`:

```python
@dataclass
class ToolConfirmationRequest:
    """Request user approval before executing a tool."""
    tool_name: str
    description: str
    request_id: str


@dataclass
class ToolConfirmationResponse:
    """User's approval/denial of a tool execution."""
    request_id: str
    approved: bool
```

- [ ] **Step 4: Rewrite `ToolDispatcher` with confirmation gate**

Replace `shannon/brain/tool_dispatch.py`:

```python
"""Tool dispatcher — routes LLM tool calls to the correct local executor."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, TYPE_CHECKING

from shannon.brain.types import LLMToolCall

if TYPE_CHECKING:
    from shannon.bus import EventBus
    from shannon.config import ToolsConfig

_SERVER_SIDE_TOOLS = {"web_search", "web_fetch", "code_execution", "memory"}

_CONFIRMATION_TIMEOUT = 120  # seconds


class ToolDispatcher:
    """Routes tool_use blocks from Claude's response to the correct executor.

    Server-side tools (web_search, web_fetch, code_execution, memory) don't need
    dispatch — results are already in the API response.
    """

    def __init__(
        self,
        computer_executor: Any = None,
        bash_executor: Any = None,
        text_editor_executor: Any = None,
        tools_config: "ToolsConfig | None" = None,
        bus: "EventBus | None" = None,
    ) -> None:
        self._computer = computer_executor
        self._bash = bash_executor
        self._text_editor = text_editor_executor
        self._tools_config = tools_config
        self._bus = bus
        self.channel_id: str = ""
        self.participants: dict[str, str] = {}
        self._pending_confirmations: dict[str, asyncio.Future[bool]] = {}

        # Subscribe to confirmation responses if bus is available
        if self._bus is not None:
            from shannon.events import ToolConfirmationResponse
            self._bus.subscribe(ToolConfirmationResponse, self._on_confirmation_response)

    def set_context(self, channel_id: str, participants: dict[str, str]) -> None:
        """Update the conversation context for the current turn."""
        self.channel_id = channel_id
        self.participants = dict(participants)

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------

    def _needs_confirmation(self, name: str) -> bool:
        """Check if a tool requires user confirmation before execution."""
        if self._tools_config is None:
            return False
        if name == "bash":
            return self._tools_config.bash.require_confirmation
        if name == "str_replace_based_edit_tool":
            return self._tools_config.text_editor.require_confirmation
        if name == "computer":
            return self._tools_config.computer_use.require_confirmation
        return False

    @staticmethod
    def _describe_tool_call(name: str, args: dict[str, Any]) -> str:
        """Produce a human-readable summary of a tool call."""
        if name == "bash":
            return f"bash: {args.get('command', '(no command)')}"
        if name == "str_replace_based_edit_tool":
            cmd = args.get("command", "?")
            path = args.get("path", "?")
            return f"text_editor: {cmd} on {path}"
        if name == "computer":
            action = args.get("action", "?")
            coord = args.get("coordinate", "")
            return f"computer: {action}" + (f" at {coord}" if coord else "")
        return f"{name}: {args}"

    async def _request_confirmation(self, name: str, args: dict[str, Any]) -> bool:
        """Publish a confirmation request and wait for a response."""
        if self._bus is None:
            return False
        from shannon.events import ToolConfirmationRequest
        request_id = str(uuid.uuid4())
        description = self._describe_tool_call(name, args)
        event = ToolConfirmationRequest(
            tool_name=name, description=description, request_id=request_id,
        )
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending_confirmations[request_id] = future
        await self._bus.publish(event)
        try:
            return await asyncio.wait_for(future, timeout=_CONFIRMATION_TIMEOUT)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending_confirmations.pop(request_id, None)

    async def _on_confirmation_response(self, event: Any) -> None:
        """Resolve a pending confirmation future."""
        future = self._pending_confirmations.get(event.request_id)
        if future is not None and not future.done():
            future.set_result(event.approved)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, tool_call: LLMToolCall) -> str | dict:
        """Route a tool call to the appropriate executor and return its result."""
        name = tool_call.name
        args = tool_call.arguments

        if name == "continue":
            return "ok"

        if name == "set_expression":
            return "ok"

        # Confirmation gate
        if self._needs_confirmation(name):
            approved = await self._request_confirmation(name, args)
            if not approved:
                return f"Tool '{name}' was denied by the user."

        if name == "bash":
            if self._bash is None:
                return "Error: bash executor is not available."
            return await self._bash.execute(args)

        if name == "str_replace_based_edit_tool":
            if self._text_editor is None:
                return "Error: text_editor executor is not available."
            return self._text_editor.execute(args)

        if name == "computer":
            if self._computer is None:
                return "Error: computer executor is not available."
            return await self._computer.execute(args)

        return f"Unknown tool: {name}"

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_continue(name: str) -> bool:
        return name == "continue"

    @staticmethod
    def is_expression(name: str) -> bool:
        return name == "set_expression"

    @staticmethod
    def is_server_side(name: str) -> bool:
        return name in _SERVER_SIDE_TOOLS
```

- [ ] **Step 5: Wire confirmation handler in `app.py`**

In `shannon/app.py`, update the dispatcher construction (around line 100):

```python
dispatcher = ToolDispatcher(
    computer_executor=computer_executor,
    bash_executor=bash_executor,
    text_editor_executor=text_editor_executor,
    tools_config=config.tools,
    bus=bus,
)
```

After constructing the dispatcher (around line 105), add the CLI confirmation handler:

```python
# CLI confirmation handler — prompts user via stdin
from shannon.events import ToolConfirmationRequest, ToolConfirmationResponse

async def _cli_confirm_handler(event: ToolConfirmationRequest) -> None:
    loop = asyncio.get_running_loop()
    answer = await loop.run_in_executor(
        None, lambda: input(f"\n[{event.tool_name}] {event.description}\nAllow? [y/N]: ")
    )
    approved = answer.strip().lower() in ("y", "yes")
    await bus.publish(ToolConfirmationResponse(
        request_id=event.request_id, approved=approved,
    ))

bus.subscribe(ToolConfirmationRequest, _cli_confirm_handler)
```

- [ ] **Step 6: Update existing tests that construct ToolDispatcher without new args**

In `tests/test_tool_dispatch.py`, update `_make_dispatcher`:

```python
def _make_dispatcher(
    computer=None,
    bash=None,
    text_editor=None,
) -> ToolDispatcher:
    return ToolDispatcher(
        computer_executor=computer,
        bash_executor=bash,
        text_editor_executor=text_editor,
    )
```

This continues to work because `tools_config` and `bus` default to `None` (confirmation disabled).

- [ ] **Step 7: Run all tests**

Run: `python3 -m pytest tests/test_tool_dispatch.py tests/test_brain.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add shannon/events.py shannon/brain/tool_dispatch.py shannon/app.py tests/test_tool_dispatch.py
git commit -m "feat: implement bus-based tool confirmation gate with CLI stdin handler (F1)"
```

---

### Task 7: Memory containment fix (F5)

**Files:**
- Modify: `shannon/tools/memory_backend.py:54-57`
- Test: `tests/test_memory_backend.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_memory_backend.py`:

```python
def test_resolve_rejects_symlink_escaping_memories_root(tmp_path):
    """A symlink inside memories/ pointing outside memories/ (but inside base_dir) must be rejected."""
    memories_dir = tmp_path / "memories"
    memories_dir.mkdir()
    # Create a file outside memories/ but inside base_dir
    secret = tmp_path / "secret.txt"
    secret.write_text("secret data")
    # Create a symlink inside memories/ pointing to the secret
    link = memories_dir / "escape"
    link.symlink_to(secret)

    backend = MemoryBackend(base_dir=str(tmp_path))
    result = backend.execute({"command": "view", "path": "/memories/escape"})
    assert "does not exist" in result or "invalid" in result.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_memory_backend.py::test_resolve_rejects_symlink_escaping_memories_root -v`
Expected: FAIL — the symlink resolves to `tmp_path/secret.txt` which passes `relative_to(self._base)`

- [ ] **Step 3: Fix containment check**

In `shannon/tools/memory_backend.py`, line 55, change:

```python
# Before:
candidate.relative_to(self._base)
# After:
candidate.relative_to(self._memories_root)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_memory_backend.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/tools/memory_backend.py tests/test_memory_backend.py
git commit -m "fix: tighten memory containment check to _memories_root (F5)"
```

---

### Task 8: Messaging fixes (F7, F8, F9, F24, F25)

**Files:**
- Modify: `shannon/messaging/manager.py`
- Modify: `shannon/messaging/providers/discord.py:44-50`
- Test: `tests/test_messaging.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_messaging.py`:

```python
@pytest.mark.asyncio
async def test_no_chat_reaction_on_non_responding_message():
    """When _should_respond is False, no ChatReaction should be published (F9)."""
    bus = EventBus()
    provider = FakeMessagingProvider()
    config = MessagingConfig(reaction_probability=1.0)  # always trigger
    manager = MessagingManager(bus=bus, providers=[provider], config=config)
    await manager.start()

    reactions: list[ChatReaction] = []
    bus.subscribe(ChatReaction, lambda e: reactions.append(e))

    # Simulate a message that won't be responded to (no mention, no reply, no conversation)
    await provider.simulate_message(
        text="hello", author="user", channel_id="ch1", message_id="m1",
    )

    # Give tasks time to run
    await asyncio.sleep(0.05)

    # Should NOT publish a ChatReaction with empty emoji
    assert len(reactions) == 0

    await manager.stop()


@pytest.mark.asyncio
async def test_no_typing_for_empty_response():
    """Empty-text ChatResponse should not trigger a typing indicator (F7)."""
    bus = EventBus()
    provider = FakeMessagingProvider()
    manager = MessagingManager(bus=bus, providers=[provider])
    await manager.start()

    await bus.publish(ChatResponse(
        text="", platform="fake", channel="ch1", reply_to="m1", reactions=["👍"],
    ))

    # Typing should not have been sent
    assert "ch1" not in provider.typing_channels
    # But reactions should still be applied
    assert ("ch1", "m1", "👍") in provider.reactions

    await manager.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_messaging.py::test_no_chat_reaction_on_non_responding_message tests/test_messaging.py::test_no_typing_for_empty_response -v`
Expected: FAIL

- [ ] **Step 3: Implement fixes in `messaging/manager.py`**

**F9 — Remove dead ChatReaction block.** In `_handle_incoming`, replace lines 133-139:

```python
        if not self._should_respond(platform, channel_id, is_reply_to_bot, is_mention, is_in_conversation):
            return
```

**F8 — Split CancelledError handling.** Replace `_debounced_publish` inner function:

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
                        return

                if provider:
                    typing_task = asyncio.create_task(_typing_loop(provider, channel_id))

                await self._bus.publish(event)
            finally:
                if typing_task is not None:
                    typing_task.cancel()
                if self._pending.get(key) is task:
                    del self._pending[key]
```

**F7 — Guard typing for empty responses.** Replace `_on_chat_response`:

```python
    async def _on_chat_response(self, event: ChatResponse) -> None:
        """Route a ChatResponse to the appropriate provider."""
        provider = self._providers.get(event.platform)
        if provider is None:
            return

        # Send message (with typing indicator) only if there's text
        if event.text:
            try:
                await provider.send_typing(event.channel)
            except Exception:
                pass
            reply_to = event.reply_to if event.reply_to else None
            await provider.send_message(event.channel, event.text, reply_to=reply_to)

        # Apply reactions
        if event.reactions and event.reply_to:
            for emoji in event.reactions:
                await provider.add_reaction(event.channel, event.reply_to, emoji)
```

- [ ] **Step 4: Fix sentence-boundary margin in `discord.py` (F25)**

In `shannon/messaging/providers/discord.py`, replace the sentence-boundary search (around line 45-50):

```python
        # Try to split on sentence boundary
        best_sentence = -1
        for punc in (". ", "! ", "? "):
            idx = remaining.rfind(punc, 0, DISCORD_MAX_LENGTH)
            if idx > best_sentence:
                best_sentence = idx + 1  # include the punctuation mark
```

(Remove the `margin = DISCORD_MAX_LENGTH - 100` variable and use `DISCORD_MAX_LENGTH` directly.)

- [ ] **Step 5: Add F24 comment**

In `shannon/brain/brain.py`, add a comment at line 149:

```python
                    # NOTE: only the first response in a continue chain gets reply_to.
                    # Reactions on follow-up messages are dropped (known limitation;
                    # fixing requires send_message to return message IDs).
                    reply_to=event.message_id if i == 0 else "",
```

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest tests/test_messaging.py tests/test_discord_provider.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add shannon/messaging/manager.py shannon/messaging/providers/discord.py shannon/brain/brain.py tests/test_messaging.py
git commit -m "fix: messaging — remove empty reaction, guard typing, fix debounce cancel, widen split margin (F7-F9, F24-F25)"
```

---

### Task 9: Vision — Webcam executor offload + release + mss thread safety (F7-webcam, F16-webcam, F17)

**Files:**
- Modify: `shannon/vision/providers/webcam.py`
- Modify: `shannon/vision/providers/screen.py:34-53`
- Modify: `shannon/vision/providers/base.py`
- Modify: `shannon/vision/manager.py:32-44`
- Modify: `shannon/app.py` (shutdown block)
- Test: `tests/test_vision.py`

- [ ] **Step 1: Add `close()` to VisionProvider base class**

In `shannon/vision/providers/base.py`:

```python
"""Abstract base class for vision capture providers."""

from abc import ABC, abstractmethod


class VisionProvider(ABC):
    @abstractmethod
    async def capture(self) -> bytes:
        """Capture an image and return it as PNG bytes."""
        ...

    @abstractmethod
    def source_name(self) -> str:
        """Return the source identifier: 'screen' or 'cam'."""
        ...

    async def close(self) -> None:
        """Release resources. Default no-op; override in providers that hold handles."""
        pass
```

- [ ] **Step 2: Fix webcam — offload to executor + implement close**

Replace `shannon/vision/providers/webcam.py`:

```python
"""Webcam capture provider using OpenCV."""

from __future__ import annotations

import asyncio

from shannon.vision.providers.base import VisionProvider


class WebcamCapture(VisionProvider):
    """Captures a frame from the default webcam as PNG bytes using OpenCV (lazy-loaded)."""

    def __init__(self, device_index: int = 0) -> None:
        self._device_index = device_index
        self._cap = None

    def _get_cap(self):
        if self._cap is None:
            import cv2
            self._cap = cv2.VideoCapture(self._device_index)
        return self._cap

    async def capture(self) -> bytes:
        """Read a frame from the webcam and return it as PNG bytes (non-blocking)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._capture_sync)

    def _capture_sync(self) -> bytes:
        """Synchronous capture implementation."""
        import cv2

        cap = self._get_cap()
        ret, frame = cap.read()
        if not ret:
            raise RuntimeError("Failed to read frame from webcam")
        success, buf = cv2.imencode(".png", frame)
        if not success:
            raise RuntimeError("Failed to encode webcam frame as PNG")
        return buf.tobytes()

    def source_name(self) -> str:
        return "cam"

    async def close(self) -> None:
        """Release the underlying VideoCapture resource."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
```

- [ ] **Step 3: Fix screen capture — create mss per-call (F17)**

Replace `_capture_sync` and remove `_get_mss`/`self._mss` in `shannon/vision/providers/screen.py`:

```python
class ScreenCapture(VisionProvider):
    """Captures the primary monitor as PNG bytes using mss."""

    def __init__(self, max_width: int = 1024, max_height: int = 768) -> None:
        self._max_width = max_width
        self._max_height = max_height

    async def capture(self) -> bytes:
        """Capture monitor[0], resize, and return PNG bytes (non-blocking)."""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._capture_sync)

    def _capture_sync(self) -> bytes:
        """Synchronous capture implementation."""
        import mss
        import mss.tools
        with mss.mss() as sct:
            monitor = sct.monitors[0]
            screenshot = sct.grab(monitor)
            png_bytes = mss.tools.to_png(screenshot.rgb, screenshot.size)
        return _resize_image(png_bytes, self._max_width, self._max_height)

    def source_name(self) -> str:
        return "screen"
```

- [ ] **Step 4: Fix interval drift in VisionManager (F20)**

Replace `run` in `shannon/vision/manager.py`:

```python
    async def run(self) -> None:
        """Start the periodic capture loop. Runs until stop() is called."""
        self._running = True
        while self._running:
            start = asyncio.get_event_loop().time()
            for provider in self._providers:
                try:
                    image = await provider.capture()
                    await self._bus.publish(
                        VisionFrame(image=image, source=provider.source_name())
                    )
                except Exception:
                    logger.debug("Capture failed for %s", provider.source_name(), exc_info=True)
            elapsed = asyncio.get_event_loop().time() - start
            await asyncio.sleep(max(0, self._interval - elapsed))
```

- [ ] **Step 5: Add provider close to app.py shutdown**

In `shannon/app.py`, in the `finally` shutdown block, after `vision_manager.stop()`, add:

```python
        # Release vision provider resources
        for vp in vision_providers:
            try:
                await vp.close()
            except Exception:
                logger.debug("Error closing vision provider", exc_info=True)
```

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest tests/test_vision.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add shannon/vision/ shannon/app.py tests/test_vision.py
git commit -m "fix: webcam executor offload, mss thread safety, vision cleanup, interval drift (F7, F16, F17, F20)"
```

---

### Task 10: Output — Piper stream fix + speak duration + VTuber error handling (F10, F12, F15-speak)

**Files:**
- Modify: `shannon/output/providers/tts/piper.py:75-96`
- Modify: `shannon/output/manager.py:70-98`
- Modify: `shannon/output/providers/vtuber/vtube_studio.py:87-158`
- Test: `tests/test_output.py`

- [ ] **Step 1: Fix PiperProvider.stream_synthesize — offload to executor (F10)**

Replace `stream_synthesize` in `shannon/output/providers/tts/piper.py`:

```python
    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Synthesize text and yield AudioChunks one sentence at a time."""
        self._load()
        assert self._voice is not None

        import asyncio

        loop = asyncio.get_running_loop()

        try:
            chunks = await loop.run_in_executor(None, self._stream_sync, text)
            for chunk in chunks:
                yield chunk
        except AttributeError:
            # Fallback: synthesize in one go and yield as single chunk
            chunk = await self.synthesize(text)
            yield chunk

    def _stream_sync(self, text: str) -> list[AudioChunk]:
        """Collect all stream chunks synchronously — runs in thread pool."""
        result = []
        for audio_bytes in self._voice.synthesize_stream_raw(text):  # type: ignore[attr-defined]
            if isinstance(audio_bytes, (bytes, bytearray)):
                raw = bytes(audio_bytes)
            else:
                raw = audio_bytes.tobytes()
            result.append(AudioChunk(
                data=raw,
                sample_rate=self._voice.config.sample_rate,  # type: ignore[attr-defined]
                channels=1,
            ))
        return result
```

- [ ] **Step 2: Fix speak duration in OutputManager (F15-speak)**

Replace `_speak` in `shannon/output/manager.py`:

```python
    async def _speak(self, text: str) -> None:
        """Synthesize *text* via TTS and emit SpeechStart/SpeechEnd events."""
        assert self._tts is not None

        try:
            phonemes = await self._tts.get_phonemes(text)
        except Exception:
            phonemes = []

        chunk = await self._tts.synthesize(text)
        duration = _estimate_duration(chunk)

        await self._bus.publish(SpeechStart(duration=duration, phonemes=phonemes))

        if self._vtuber is not None:
            await self._vtuber.start_speaking(phonemes=phonemes)

        # Hold mouth open for the estimated audio duration
        if duration > 0:
            await asyncio.sleep(duration)

        if self._vtuber is not None:
            await self._vtuber.stop_speaking()

        await self._bus.publish(SpeechEnd())
```

Add `import asyncio` to the imports at the top of the file if not already present.

- [ ] **Step 3: Add VTuber error handling (F12)**

In `shannon/output/providers/vtuber/vtube_studio.py`:

**3a.** Check auth response at line 125 — replace `await self._recv()` with:

```python
            resp = await self._recv()
            if not resp.get("data", {}).get("authenticated"):
                import logging
                logging.getLogger(__name__).warning("VTube Studio authentication failed")
                await self.disconnect()
                return
```

**3b.** Wrap `_send` for disconnection resilience — replace `_send`:

```python
    async def _send(self, message_type: str, data: dict[str, Any]) -> None:
        """Serialise and send a VTS API message. No-op if disconnected."""
        if self._ws is None:
            return
        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": str(uuid.uuid4()),
            "messageType": message_type,
            "data": data,
        }
        try:
            await self._ws.send(json.dumps(payload))
        except Exception:
            import logging
            logging.getLogger(__name__).warning("VTube Studio connection lost")
            self._ws = None
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_output.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add shannon/output/ tests/test_output.py
git commit -m "fix: piper stream executor offload, speak duration wait, VTuber error handling (F10, F12, F15)"
```

---

### Task 11: Shutdown order + GenerationRequest comment (F18, F22)

**Files:**
- Modify: `shannon/app.py:284-314`
- Modify: `shannon/brain/types.py:22-29`

- [ ] **Step 1: Fix shutdown order in `app.py`**

Replace the `finally` block (lines 288-314):

```python
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        # Stop modules in dependency order: messaging first (stop accepting),
        # then autonomy/vision, then bash, then output, then VTuber/computer.
        await messaging_manager.stop()
        autonomy_loop.stop()
        vision_manager.stop()

        # Release vision provider resources
        for vp in vision_providers:
            try:
                await vp.close()
            except Exception:
                logger.debug("Error closing vision provider", exc_info=True)

        await bash_executor.close()
        output_manager.stop()

        if vtuber_provider is not None:
            try:
                await vtuber_provider.disconnect()
            except Exception:
                logger.debug("Error disconnecting VTuber", exc_info=True)

        if computer_executor is not None:
            computer_executor.shutdown()

        logger.info("%s shutting down.", name)
```

- [ ] **Step 2: Add GenerationRequest docstring note (F22)**

In `shannon/brain/types.py`, update the `GenerationRequest` docstring:

```python
@dataclass(frozen=True)
class GenerationRequest:
    """Everything the brain needs to produce a response — immutable after creation.

    Note: frozen=True prevents field reassignment. Contained collections (images,
    participants) are still mutable by convention but must not be modified after creation.
    """
    text: str
    images: list[bytes] = field(default_factory=list)
    dynamic_context: str = ""
    tool_mode: str = "full"
    channel_id: str = ""
    participants: dict[str, str] = field(default_factory=dict)
```

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add shannon/app.py shannon/brain/types.py
git commit -m "fix: correct shutdown order, add GenerationRequest docstring (F18, F22)"
```

---

### Task 12: Final integration verification

- [ ] **Step 1: Run the full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS (381+ tests)

- [ ] **Step 2: Verify no regressions with a quick grep for known patterns**

```bash
# Verify no __new__ in _build_defaults
grep -n "__new__" shannon/config.py
# Verify _memories_root in containment check
grep -n "relative_to" shannon/tools/memory_backend.py
# Verify require_confirmation is actually checked
grep -n "require_confirmation" shannon/brain/tool_dispatch.py
# Verify no assert in brain.py (except test files)
grep -n "^        assert " shannon/brain/brain.py
```

Expected:
- `__new__` — no matches in `_build_defaults`
- `relative_to` — shows `self._memories_root`
- `require_confirmation` — shows `_needs_confirmation` checks
- No bare `assert` in brain.py process_input

- [ ] **Step 3: Done**

All 25 findings addressed across 11 commits.
