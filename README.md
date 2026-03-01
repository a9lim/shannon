# Shannon

An LLM-powered autonomous assistant that communicates over Discord and Signal, executes system commands, browses the web, delegates tasks to Claude Code, drives interactive CLI programs, schedules its own work, reacts to external webhooks, maintains persistent memory, and plans multi-step tasks.

## Features

- **Multi-platform messaging** — Discord (mentions, DMs, threads) and Signal (signal-cli or REST API)
- **Dual LLM support** — Anthropic Claude or any OpenAI-compatible local endpoint (ollama, llama.cpp, vllm) with ReAct fallback for models without native tool calling
- **Tool ecosystem** — Shell execution, Playwright browser automation, Claude Code delegation, interactive PTY sessions, persistent memory, multi-step planning
- **Permission system** — 4-tier auth (public → trusted → operator → admin) with per-tool gating, per-user rate limiting, and sudo escalation with admin approval
- **Context management** — SQLite-backed conversation history with automatic LLM-based summarization when approaching token limits
- **Persistent memory** — Cross-session key-value store for facts, preferences, and project state; searchable, categorized, and automatically injected into the LLM system prompt
- **Webhook triggers** — React to GitHub pushes, Sentry alerts, CI failures, and arbitrary webhooks with HMAC signature validation and LLM-powered responses
- **Multi-step planning** — Decompose complex goals into step-by-step plans, execute sequentially with progress updates, handle failures with retry/skip/abort
- **Pause/resume** — Temporarily suspend autonomous behaviors (cron, heartbeat, webhooks) while still responding to direct messages; supports timed auto-resume
- **Task scheduling** — Cron-based job scheduling with heartbeat monitoring; Shannon can schedule its own recurring tasks
- **Intelligent chunking** — Splits long responses at natural boundaries (paragraph, sentence, clause) while preserving code blocks

## Quick Start

```bash
# Install
pip install -e .

# Set credentials
export SHANNON_LLM__API_KEY="your-anthropic-key"
export SHANNON_DISCORD__TOKEN="your-discord-bot-token"

# Run
python -m shannon.main
```

Or use a config file:

```bash
cp config.example.yaml ~/.shannon/config.yaml
# Edit ~/.shannon/config.yaml with your settings
python -m shannon.main
```

## Configuration

Shannon loads config from environment variables (`SHANNON_` prefix, `__` for nesting) and an optional YAML file. Env vars take precedence.

### Config file location

| Platform | Default path |
|----------|-------------|
| Windows | `%APPDATA%\shannon\config.yaml` (e.g. `C:\Users\<you>\AppData\Roaming\shannon\config.yaml`) |
| macOS | `~/Library/Application Support/shannon/config.yaml` |
| Linux | `~/.config/shannon/config.yaml` (or `$XDG_CONFIG_HOME/shannon/`) |

You can override this with `--config path/to/config.yaml`, the `SHANNON_CONFIG` env var, or `SHANNON_CONFIG_DIR` to change the directory.

To get started, copy the example config:

```bash
# Linux/macOS
mkdir -p ~/.config/shannon
cp config.example.yaml ~/.config/shannon/config.yaml

# Windows (cmd)
mkdir "%APPDATA%\shannon"
copy config.example.yaml "%APPDATA%\shannon\config.yaml"
```

Then fill in at minimum `llm.api_key` and `discord.token` (or their env var equivalents `SHANNON_LLM__API_KEY` and `SHANNON_DISCORD__TOKEN`).

| Section | Key fields |
|---------|-----------|
| `llm` | `provider` (anthropic/local), `model`, `api_key`, `local_endpoint`, `max_tokens`, `temperature` |
| `discord` | `token`, `guild_ids` (empty = all) |
| `signal` | `phone_number`, `mode` (cli/rest), `signal_cli_path`, `rest_api_url` |
| `auth` | `admin_users`, `operator_users`, `trusted_users`, `rate_limit_per_minute`, `sudo_timeout_seconds` |
| `browser` | `headless`, `browser` (chromium/firefox/webkit) |
| `webhooks` | `enabled`, `port` (8420), `bind`, `endpoints` (list of name/path/secret/channel/prompt_template) |

User IDs in auth lists use `platform:user_id` format (e.g., `discord:123456`) or bare IDs for all platforms.

See [`config.example.yaml`](config.example.yaml) for all options.

## Chat Commands

| Command | Description |
|---------|-------------|
| `/forget` | Clear conversation history for the channel |
| `/context` | Show context stats (message count, chars) |
| `/summarize` | Generate an LLM summary of the conversation |
| `/jobs` | List scheduled cron jobs |
| `/sudo <action>` | Request permission elevation |
| `/sudo approve <id>` | Admin: approve a sudo request |
| `/memory` | List all stored memories |
| `/memory search <query>` | Search memories by key or value |
| `/memory clear` | Clear all memories (Admin only) |
| `/pause [duration]` | Pause autonomous behaviors (Operator). Optional duration: `2h`, `30m`, `1h30m` |
| `/resume` | Resume autonomous behaviors (Operator). Reports missed events |
| `/status` | Show whether Shannon is paused or active |
| `/help` | Show available commands |

## Tools

| Tool | Permission | Description |
|------|-----------|-------------|
| `shell` | Operator | Execute system commands with timeout and safety blocklist |
| `browser` | Trusted | Navigate, search, screenshot, click, type, extract, PDF via Playwright |
| `claude_code` | Operator | Delegate complex coding tasks to Claude Code CLI |
| `interactive` | Operator | Drive interactive CLI programs (python, ssh, etc.) via PTY |
| `memory_set` | Trusted | Store a key-value pair in persistent memory |
| `memory_get` | Trusted | Retrieve a memory by key or search by query |
| `memory_delete` | Operator | Delete a memory entry |
| `plan` | Operator | Create and execute a multi-step plan for a complex goal |

Tools are only available to users meeting the required permission level. The LLM only sees tools the user is authorized to use.

## Architecture

```
Discord/Signal → Transport → EventBus → MessageHandler.handle()
                                              ↓
                                     rate limit + auth check
                                              ↓
                                     load context (SQLite) + memory
                                              ↓
                                     LLM call with tool schemas
                                              ↓
                                     tool-use loop (≤10 iterations)
                                              ↓
                                     store response + publish MessageOutgoing
                                              ↓
                              EventBus → Transport → Discord/Signal

GitHub/Sentry/HTTP → WebhookServer → validate HMAC → normalize → EventBus
                                                                     ↓
                                                          (same pipeline as above)
```

All components communicate through the async event bus and have `start()`/`stop()` lifecycle methods. Tools with heavy resources (browser, interactive sessions) initialize lazily on first use. The pause manager can suspend autonomous behaviors (cron, heartbeat, webhooks) without stopping the bot.

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run a single test
pytest tests/test_auth.py::TestSudo::test_approve_sudo -v

# Dry-run mode (no LLM calls)
python -m shannon.main --dry-run --log-level DEBUG
```

## Requirements

- Python 3.11+
- For browser tool: `playwright install chromium`
- For Signal: [signal-cli](https://github.com/AsamK/signal-cli) or [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api)
- For Claude Code tool: [Claude Code CLI](https://claude.ai/code) installed and on PATH
