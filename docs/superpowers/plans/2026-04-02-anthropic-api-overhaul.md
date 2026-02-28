# Anthropic API Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Shannon's entire LLM and tool layer with Anthropic's native API — adaptive thinking, streaming, prompt caching, compaction, 1M context, and native tools (computer use, bash, text editor, code execution, memory, web search/fetch).

**Architecture:** Single Claude provider (no Ollama). Brain decomposed into brain.py (events + conversation), claude.py (API client), tool_dispatch.py (routing), tool_registry.py (tool list). New executor modules for client-side tools. Server-side tools handled by Anthropic.

**Tech Stack:** Python 3.11+, anthropic SDK, pyautogui (computer use), mss (screenshots), pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-04-02-anthropic-api-overhaul-design.md`

---

## File Map

### New files
- `shannon/brain/types.py` — LLMMessage, LLMToolCall, LLMResponse dataclasses
- `shannon/brain/claude.py` — Anthropic API client (streaming, caching, compaction, adaptive thinking)
- `shannon/brain/tool_registry.py` — ToolRegistry: builds tools list from config
- `shannon/brain/tool_dispatch.py` — ToolDispatcher: routes tool_use blocks to executors
- `shannon/computer/__init__.py`
- `shannon/computer/screenshot.py` — screen capture + resolution scaling
- `shannon/computer/executor.py` — computer use action execution
- `shannon/tools/__init__.py`
- `shannon/tools/bash_executor.py` — persistent bash session
- `shannon/tools/text_editor_executor.py` — file view/edit operations
- `shannon/tools/memory_backend.py` — Anthropic memory protocol backend
- `tests/test_types.py`
- `tests/test_tool_registry.py`
- `tests/test_tool_dispatch.py`
- `tests/test_bash_executor.py`
- `tests/test_text_editor_executor.py`
- `tests/test_memory_backend.py`
- `tests/test_computer_executor.py`
- `tests/test_claude_client.py`

### Modified files
- `shannon/config.py` — replace ActionsConfig with ToolsConfig, update LLMConfig
- `shannon/events.py` — remove ActionRequest, ActionResult
- `shannon/brain/brain.py` — rewrite: events + conversation only, delegate to new modules
- `shannon/brain/prompt.py` — update response format instructions for new tools
- `shannon/app.py` — rewire: no ActionManager, no Ollama, direct Claude + executors
- `pyproject.toml` — anthropic to core deps, remove ollama/web/actions groups
- `CLAUDE.md` — update for new architecture
- `tests/test_brain.py` — rewrite for new imports and architecture
- `tests/test_config.py` — rewrite for new config shape
- `tests/test_events.py` — remove ActionRequest/ActionResult tests
- `tests/test_integration.py` — rewrite for new architecture
- `tests/test_app.py` — update for new config

### Deleted files
- `shannon/actions/` (entire directory)
- `shannon/brain/providers/ollama.py`
- `shannon/brain/providers/memory_base.py`
- `shannon/brain/providers/memory_markdown.py`
- `shannon/brain/providers/base.py`
- `shannon/brain/providers/claude.py` (moves to `shannon/brain/claude.py`)
- `shannon/brain/memory.py`
- `tests/test_actions.py`
- `tests/test_memory.py`

---

## Tasks

Tasks are ordered so that each builds on the previous. New modules are built first (with tests), then the brain is rewired, then old code is deleted.

### Task 1: Types module

Create the shared data types used by the new brain modules.

**Files:**
- Create: `shannon/brain/types.py`
- Create: `tests/test_types.py`

- [ ] **Step 1: Write tests for types**

Create `tests/test_types.py` testing LLMMessage (basic, images, defaults), LLMToolCall (fields), LLMResponse (defaults, with tool_calls, stop_reason). 5 test functions.

- [ ] **Step 2: Run tests — verify FAIL (ModuleNotFoundError)**

Run: `python3 -m pytest tests/test_types.py -v`

- [ ] **Step 3: Implement types.py**

Create `shannon/brain/types.py` with three dataclasses:
- `LLMMessage(role, content: str | list[dict], images=[], tool_calls=[], tool_results=[])` — content is `str | list` to support Anthropic content blocks (compaction)
- `LLMToolCall(id, name, arguments)`
- `LLMResponse(text, tool_calls=[], stop_reason="")`

- [ ] **Step 4: Run tests — verify PASS**

Run: `python3 -m pytest tests/test_types.py -v`

- [ ] **Step 5: Commit**

Message: `feat: add brain/types.py with LLMMessage, LLMToolCall, LLMResponse`

---

### Task 2: Config overhaul

Replace `ActionsConfig` + `ProvidersConfig` with `ToolsConfig` + flat config.

**Files:**
- Modify: `shannon/config.py`
- Rewrite: `tests/test_config.py`

- [ ] **Step 1: Write new config tests**

Test: LLMConfig defaults (model=claude-opus-4-6, max_tokens=16000, thinking=True, compaction=True), ToolsConfig defaults (ComputerUseConfig, BashConfig with blocklist, TextEditorConfig), `apply_dangerously_skip_permissions()` sets require_confirmation=False, load_config with partial overrides. ~20 test functions.

- [ ] **Step 2: Run tests — verify FAIL (imports don't exist)**

Run: `python3 -m pytest tests/test_config.py -v`

- [ ] **Step 3: Rewrite config.py**

Remove: `ProvidersConfig`, `ActionsConfig`, `ShellActionConfig`, `BrowserActionConfig`, `MouseActionConfig`, `KeyboardActionConfig`, `LLMConfig.type`.
Add: `ComputerUseConfig`, `BashConfig`, `TextEditorConfig`, `ToolsConfig`.
Flatten: `llm`, `tts`, `stt`, etc. are top-level in `ShannonConfig` (no more `ProvidersConfig` wrapper).
Update `apply_dangerously_skip_permissions()` to set `require_confirmation=False` on tools.

- [ ] **Step 4: Run config tests — verify PASS**

Run: `python3 -m pytest tests/test_config.py -v`

- [ ] **Step 5: Commit**

Message: `feat: replace ActionsConfig with ToolsConfig, flatten config hierarchy`

Note: other tests will break at this point due to old config imports. This is expected.

---

### Task 3: Bash executor

**Files:**
- Create: `shannon/tools/__init__.py`
- Create: `shannon/tools/bash_executor.py`
- Create: `tests/test_bash_executor.py`

- [ ] **Step 1: Write tests**

Test: execute echo (check output), persistent env vars across commands, persistent working directory, restart clears state, blocklist rejects dangerous commands, timeout kills slow commands, close terminates session, no-command error. ~10 test functions.

- [ ] **Step 2: Run tests — verify FAIL**

Run: `python3 -m pytest tests/test_bash_executor.py -v`

- [ ] **Step 3: Implement bash_executor.py**

`BashExecutor(config: BashConfig)`:
- `_ensure_session()` — starts `/bin/bash --norc --noprofile` subprocess if not running
- `_check_blocklist(command)` — returns error string if blocked, else None
- `execute(params)` — handles `command` and `restart` params. Uses sentinel echo to detect end of output. Enforces timeout. Truncates large output (50K chars).
- `close()` — terminates subprocess

- [ ] **Step 4: Run tests — verify PASS**

Run: `python3 -m pytest tests/test_bash_executor.py -v`

- [ ] **Step 5: Commit**

Message: `feat: persistent bash session executor for bash_20250124 tool`

---

### Task 4: Text editor executor

**Files:**
- Create: `shannon/tools/text_editor_executor.py`
- Create: `tests/test_text_editor_executor.py`

- [ ] **Step 1: Write tests**

Test: view file (with line numbers), view directory, view nonexistent, view_range, create file, create already-exists error, str_replace (single match), str_replace no match, str_replace multiple matches, insert at line. All use tmp_path fixture. ~14 test functions.

- [ ] **Step 2: Run tests — verify FAIL**

Run: `python3 -m pytest tests/test_text_editor_executor.py -v`

- [ ] **Step 3: Implement text_editor_executor.py**

`TextEditorExecutor(config: TextEditorConfig)`:
- `execute(params)` — dispatches to _view, _create, _str_replace, _insert
- `_view(path, view_range)` — file contents with 6-char right-aligned line numbers + tab, or directory listing with sizes
- `_create(path, file_text)` — creates file, errors if exists
- `_str_replace(path, old_str, new_str)` — exact single match replace, errors on 0 or 2+ matches
- `_insert(path, insert_line, insert_text)` — insert at line number

Error messages match Anthropic's documented format exactly.

- [ ] **Step 4: Run tests — verify PASS**

Run: `python3 -m pytest tests/test_text_editor_executor.py -v`

- [ ] **Step 5: Commit**

Message: `feat: text editor executor for text_editor_20250728 tool`

---

### Task 5: Memory backend

**Files:**
- Create: `shannon/tools/memory_backend.py`
- Create: `tests/test_memory_backend.py`

- [ ] **Step 1: Write tests**

Test: view empty directory, create + view file, create already-exists, str_replace, insert, delete file, rename, path traversal blocked. All use tmp_path fixture with a `memories/` subdirectory. ~10 test functions.

- [ ] **Step 2: Run tests — verify FAIL**

Run: `python3 -m pytest tests/test_memory_backend.py -v`

- [ ] **Step 3: Implement memory_backend.py**

`MemoryBackend(base_dir: str)`:
- `_resolve(virtual_path)` — maps `/memories/...` to local path, returns None if traversal detected
- `execute(params)` — dispatches to view, create, str_replace, insert, delete, rename
- All commands use the same format as Anthropic's documented memory tool responses

- [ ] **Step 4: Run tests — verify PASS**

Run: `python3 -m pytest tests/test_memory_backend.py -v`

- [ ] **Step 5: Commit**

Message: `feat: memory backend implementing memory_20250818 protocol`

---

### Task 6: Screenshot module

**Files:**
- Create: `shannon/computer/__init__.py`
- Create: `shannon/computer/screenshot.py`
- Create: `tests/test_screenshot.py`

- [ ] **Step 1: Write tests**

Test: scale factor is 1.0 for small screens, scale factor < 1.0 for large screens, scale_to_real identity when no scaling, scale_to_real maps back correctly, scaled dimensions within API limits. 5 test functions. No mss/PIL dependency needed — tests only exercise the math.

- [ ] **Step 2: Run tests — verify FAIL**

Run: `python3 -m pytest tests/test_screenshot.py -v`

- [ ] **Step 3: Implement screenshot.py**

`ScreenCapture(real_width, real_height)`:
- `_compute_scale()` — min(1.0, 1568/long_edge, sqrt(1_150_000/total_pixels))
- `scaled_width`, `scaled_height` properties
- `scale_to_real(x, y)` — maps Claude's coordinates back to real space
- `capture()` — uses mss + PIL (lazy import), returns scaled PNG bytes
- `capture_base64()` — base64-encoded PNG string

- [ ] **Step 4: Run tests — verify PASS**

Run: `python3 -m pytest tests/test_screenshot.py -v`

- [ ] **Step 5: Commit**

Message: `feat: screen capture with resolution scaling for computer use`

---

### Task 7: Computer use executor

**Files:**
- Create: `shannon/computer/executor.py`
- Create: `tests/test_computer_executor.py`

- [ ] **Step 1: Write tests**

Test: screenshot returns image dict, left_click calls pyautogui.click, type calls pyautogui.typewrite, key calls pyautogui.hotkey, mouse_move calls pyautogui.moveTo, scroll calls pyautogui.scroll, unknown action returns error. All use unittest.mock to patch pyautogui. ~7 test functions.

- [ ] **Step 2: Run tests — verify FAIL**

Run: `python3 -m pytest tests/test_computer_executor.py -v`

- [ ] **Step 3: Implement executor.py**

`ComputerUseExecutor(config: ComputerUseConfig)`:
- `execute(params)` — dispatches on `action` field
- `_screenshot()` — returns `{"type": "image", "source": {"type": "base64", ...}}`
- `_execute_sync(action, params)` — runs pyautogui actions in executor thread. Handles all 15+ actions from computer_20251124 spec. Coordinates scaled via ScreenCapture.

- [ ] **Step 4: Run tests — verify PASS**

Run: `python3 -m pytest tests/test_computer_executor.py -v`

- [ ] **Step 5: Commit**

Message: `feat: computer use executor for computer_20251124 tool`

---

### Task 8: Tool registry

**Files:**
- Create: `shannon/brain/tool_registry.py`
- Create: `tests/test_tool_registry.py`

- [ ] **Step 1: Write tests**

Test: builds all 9 tools, computer has display dimensions from config, disabled tools excluded, Anthropic tools have type field, user-defined tools have input_schema, beta_headers includes computer-use/compact/context-1m, beta_headers excludes computer-use when disabled. ~8 test functions.

- [ ] **Step 2: Run tests — verify FAIL**

Run: `python3 -m pytest tests/test_tool_registry.py -v`

- [ ] **Step 3: Implement tool_registry.py**

`ToolRegistry(config: ShannonConfig)`:
- `build()` — returns `list[dict]` with all enabled tools in Anthropic API format
- `beta_headers()` — returns list of beta header strings based on config

- [ ] **Step 4: Run tests — verify PASS**

Run: `python3 -m pytest tests/test_tool_registry.py -v`

- [ ] **Step 5: Commit**

Message: `feat: tool registry builds Anthropic API tools list from config`

---

### Task 9: Tool dispatcher

**Files:**
- Create: `shannon/brain/tool_dispatch.py`
- Create: `tests/test_tool_dispatch.py`

- [ ] **Step 1: Write tests**

Test: routes bash/text_editor/memory/computer to correct executor (using AsyncMock/MagicMock), expression returns confirmation string, continue returns confirmation, unknown tool returns error, is_continue/is_expression/is_server_side helpers. ~11 test functions.

- [ ] **Step 2: Run tests — verify FAIL**

Run: `python3 -m pytest tests/test_tool_dispatch.py -v`

- [ ] **Step 3: Implement tool_dispatch.py**

`ToolDispatcher(computer_executor, bash_executor, text_editor_executor, memory_backend)`:
- `dispatch(tool_call: LLMToolCall)` — routes by name, returns result
- `is_continue(name)`, `is_expression(name)`, `is_server_side(name)` — static helpers

- [ ] **Step 4: Run tests — verify PASS**

Run: `python3 -m pytest tests/test_tool_dispatch.py -v`

- [ ] **Step 5: Commit**

Message: `feat: tool dispatcher routes tool calls to executors`

---

### Task 10: Claude API client

**Files:**
- Create: `shannon/brain/claude.py`
- Create: `tests/test_claude_client.py`

- [ ] **Step 1: Write tests**

Test: _build_messages extracts system, _build_messages adds cache_control to system, _build_messages handles images, _build_messages preserves content blocks (compaction), _parse_response text only, _parse_response with tool_use, _parse_response skips server blocks. ~7 test functions. No actual API calls — test internal conversion methods.

- [ ] **Step 2: Run tests — verify FAIL**

Run: `python3 -m pytest tests/test_claude_client.py -v`

- [ ] **Step 3: Implement claude.py**

`ClaudeClient(config: LLMConfig)`:
- `_build_messages(messages)` — returns (system_blocks with cache_control, api_messages). Handles: system extraction, images→base64, tool_calls, tool_results, content block passthrough (compaction).
- `_parse_response(response)` — extracts text + tool_use, skips server blocks, captures stop_reason.
- `generate(messages, tools, betas)` — uses `client.beta.messages.stream()` + `get_final_message()`. Passes adaptive thinking, compaction context_management, beta headers.

- [ ] **Step 4: Run tests — verify PASS**

Run: `python3 -m pytest tests/test_claude_client.py -v`

- [ ] **Step 5: Commit**

Message: `feat: Claude API client with streaming, caching, compaction, adaptive thinking`

---

### Task 11: Update events.py

**Files:**
- Modify: `shannon/events.py`
- Modify: `tests/test_events.py`

- [ ] **Step 1: Remove ActionRequest and ActionResult from events.py**

Delete the two dataclasses and their imports.

- [ ] **Step 2: Remove corresponding tests from test_events.py**

Remove 5 test functions: test_action_request_construction, test_action_request_default_params, test_action_result_success, test_action_result_failure, test_action_result_with_screenshot. Remove ActionRequest/ActionResult from import line.

- [ ] **Step 3: Run tests — verify PASS**

Run: `python3 -m pytest tests/test_events.py -v`

- [ ] **Step 4: Commit**

Message: `refactor: remove ActionRequest and ActionResult events`

---

### Task 12: Update prompt builder

**Files:**
- Modify: `shannon/brain/prompt.py`

- [ ] **Step 1: Update response format for new tools**

Replace references to old tools (run_shell, browse, move_mouse, press_keys, save_memory) with new Anthropic tools (bash, computer, str_replace_based_edit_tool, memory, web_search).

- [ ] **Step 2: Commit**

Message: `refactor: update prompt builder for Anthropic native tools`

---

### Task 13: Rewrite brain.py + tests

**Files:**
- Rewrite: `shannon/brain/brain.py`
- Rewrite: `tests/test_brain.py`

- [ ] **Step 1: Write new brain tests**

Test with FakeClaude, FakeDispatcher, FakeRegistry:
- brain handles UserInput → LLMResponseEvent
- brain handles ChatMessage → ChatResponse with correct platform/channel/reply_to
- brain emits ExpressionChange for set_expression tool calls
- prompt builder test

~4 test functions.

- [ ] **Step 2: Run tests — verify FAIL (old Brain constructor)**

Run: `python3 -m pytest tests/test_brain.py -v`

- [ ] **Step 3: Rewrite brain.py**

`Brain(bus, claude, dispatcher, registry, config)`:
- Event handlers: _on_user_input, _on_chat_message, _on_autonomous_trigger, _on_vision_frame
- `_process_input(text, images)` — builds messages, calls claude.generate(), processes tool calls via dispatcher, handles continue/expression/server-side/pause_turn, emits LLMResponseEvent and ChatResponse events

- [ ] **Step 4: Run tests — verify PASS**

Run: `python3 -m pytest tests/test_brain.py -v`

- [ ] **Step 5: Commit**

Message: `refactor: rewrite brain.py with Claude client, dispatcher, registry`

---

### Task 14: Delete old code

- [ ] **Step 1: Delete old modules**

Delete: `shannon/actions/` (entire directory), `shannon/brain/providers/` (entire directory), `shannon/brain/memory.py`

- [ ] **Step 2: Delete old tests**

Delete: `tests/test_actions.py`, `tests/test_memory.py`

- [ ] **Step 3: Commit**

Message: `refactor: delete actions/, old providers, old memory system`

---

### Task 15: Rewrite integration tests + app.py

**Files:**
- Rewrite: `tests/test_integration.py`
- Rewrite: `shannon/app.py`
- Update: `tests/test_app.py`
- Update: `tests/test_autonomy.py` (fix config imports if needed)
- Update: `tests/test_output.py` (fix config imports if needed)

- [ ] **Step 1: Rewrite test_integration.py**

Use FakeClaude/FakeDispatcher/FakeRegistry pattern. Test full pipeline (UserInput → LLMResponseEvent) and chat round trip (ChatMessage → ChatResponse). ~2 test functions.

- [ ] **Step 2: Rewrite app.py**

Initialize: ClaudeClient, BashExecutor, TextEditorExecutor, MemoryBackend, ComputerUseExecutor (try/except ImportError), ToolDispatcher, ToolRegistry, Brain. Use flat config (config.llm, config.tts, not config.providers.llm). Remove ActionManager, Ollama, old memory.

- [ ] **Step 3: Fix remaining test imports**

Update test_app.py, test_autonomy.py, test_output.py if they reference old config paths (e.g. `config.providers.llm`).

- [ ] **Step 4: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

Message: `refactor: rewrite app.py and integration tests for new architecture`

---

### Task 16: Update dependencies + CLAUDE.md

**Files:**
- Modify: `pyproject.toml`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update pyproject.toml**

Move `anthropic>=0.40.0` to core dependencies. Remove: `claude`, `ollama`, `web`, `actions` groups. Remove: `httpx`, `aiohttp`, `duckduckgo-search`, `playwright`. Add `Pillow>=10.0.0` to vision group (needed for screenshot scaling). Version bump to 0.2.0.

- [ ] **Step 2: Update CLAUDE.md**

New project layout, new tool set, removed modules, updated config structure, updated event flow, updated credentials section.

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

Message: `chore: update deps (anthropic core), update CLAUDE.md for new architecture`

---

### Task 17: Final verification

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -v`

- [ ] **Step 2: Check for orphan imports**

Grep for: `from shannon.actions`, `from shannon.brain.providers`, `from shannon.brain.memory`, `ActionRequest`, `ActionResult`, `OllamaProvider`. All should return no matches.

- [ ] **Step 3: Check old files deleted**

Verify `shannon/actions/`, `shannon/brain/providers/`, `shannon/brain/memory.py` don't exist.

- [ ] **Step 4: Verify project installs cleanly**

Run: `pip install -e ".[dev]"`
Run: `python3 -c "from shannon.brain.brain import Brain; print('OK')"`

- [ ] **Step 5: Final commit if needed**

Run: `git status` — should show nothing to commit.
