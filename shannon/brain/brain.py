"""Brain manager — central intelligence for Shannon."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from shannon.brain.prompt import PromptBuilder
from shannon.brain.reactions import extract_reactions
from shannon.brain.types import LLMMessage, LLMToolCall, LLMResponse
from shannon.bus import EventBus
from shannon.config import ShannonConfig
from shannon.events import (
    AutonomousTrigger,
    ChatMessage,
    ChatResponse,
    ExpressionChange,
    LLMResponse as LLMResponseEvent,
    UserInput,
    VisionFrame,
)

if TYPE_CHECKING:
    from shannon.brain.claude import ClaudeClient
    from shannon.brain.tool_dispatch import ToolDispatcher
    from shannon.brain.tool_registry import ToolRegistry

MAX_CONTINUE_DEFAULT = 5


def _tool_content(result: object) -> str | list[dict]:
    """Normalize a tool executor result for the Anthropic tool_result format.

    Dicts (e.g. screenshot image blocks) are wrapped in a list; everything
    else is stringified.
    """
    if isinstance(result, dict):
        return [result]
    return str(result)

logger = logging.getLogger(__name__)


class Brain:
    """Central intelligence module. Subscribes to input events and drives the LLM."""

    def __init__(
        self,
        bus: EventBus,
        claude: ClaudeClient,
        dispatcher: ToolDispatcher,
        registry: ToolRegistry,
        config: ShannonConfig,
    ) -> None:
        self._bus = bus
        self._claude = claude
        self._dispatcher = dispatcher
        self._registry = registry
        self._config = config
        self._history: list[LLMMessage] = []
        self._vision_buffer: list[VisionFrame] = []
        self._prompt_builder: PromptBuilder | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Load personality and subscribe to bus events."""
        self._prompt_builder = self._load_prompt_builder()

        self._bus.subscribe(UserInput, self._on_user_input)
        self._bus.subscribe(ChatMessage, self._on_chat_message)
        self._bus.subscribe(AutonomousTrigger, self._on_autonomous_trigger)
        self._bus.subscribe(VisionFrame, self._on_vision_frame)

    def _load_prompt_builder(self) -> PromptBuilder:
        prompt_file = Path(self._config.personality.prompt_file)
        if prompt_file.exists():
            personality_text = prompt_file.read_text(encoding="utf-8")
        else:
            personality_text = (
                f"You are {self._config.personality.name}, an AI assistant."
            )
        return PromptBuilder(
            personality_text=personality_text,
            name=self._config.personality.name,
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _on_user_input(self, event: UserInput) -> None:
        logger.debug("Received UserInput: %r", event.text)
        await self._process_input(text=event.text, images=[])

    async def _on_chat_message(self, event: ChatMessage) -> None:
        logger.debug("Received ChatMessage from %s/%s: %r", event.platform, event.channel, event.text)

        # Extract images and text from attachments
        images: list[bytes] = []
        text = event.text
        for att in event.attachments:
            ct = att.get("content_type", "")
            if ct.startswith("image/"):
                images.append(att["data"])
            elif ct.startswith("text/"):
                file_text = att["data"].decode("utf-8", errors="replace")
                text += f"\n[File: {att['filename']}]\n{file_text}"
            else:
                text += f"\n[Attached file: {att['filename']}]"

        # Build system suffix from emoji and participants
        suffix_parts: list[str] = []
        if event.custom_emojis:
            suffix_parts.append(event.custom_emojis)
        if event.participants:
            admin_ids = self._config.messaging.admin_ids
            names = []
            for uid, display_name in event.participants.items():
                if uid in admin_ids:
                    names.append(f"{display_name} (admin)")
                else:
                    names.append(display_name)
            suffix_parts.append(f"Participants: {', '.join(names)}")
        dynamic_context = "\n".join(suffix_parts)

        responses = await self._process_input(text=text, images=images, dynamic_context=dynamic_context, tool_mode="chat")
        for i, response_text in enumerate(responses):
            clean_text, reactions = extract_reactions(response_text)
            if clean_text or reactions:
                await self._bus.publish(
                    ChatResponse(
                        text=clean_text,
                        platform=event.platform,
                        channel=event.channel,
                        reply_to=event.message_id if i == 0 else "",
                        reactions=reactions,
                    )
                )

        # Fail-safe: emit warning reaction if all responses are empty
        has_content = any(r.strip() for r in responses)
        if not has_content:
            await self._bus.publish(
                ChatResponse(
                    text="",
                    platform=event.platform,
                    channel=event.channel,
                    reply_to=event.message_id,
                    reactions=["⚠️"],
                )
            )

    async def _on_autonomous_trigger(self, event: AutonomousTrigger) -> None:
        await self._process_input(
            text=f"[Autonomous trigger: {event.reason}] {event.context}",
            images=[],
            tool_mode="chat",
        )

    async def _on_vision_frame(self, event: VisionFrame) -> None:
        self._vision_buffer.append(event)
        if len(self._vision_buffer) > 1:
            self._vision_buffer = self._vision_buffer[-1:]

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def _process_input(self, text: str, images: list[bytes], dynamic_context: str = "", tool_mode: str = "full") -> list[str]:
        """Build context, call LLM, process tool calls, emit events.

        Returns a list of response texts. Multiple entries when the LLM uses
        the ``continue`` tool to send follow-up messages.
        """
        assert self._prompt_builder is not None, "Brain.start() must be called before processing input"

        async with self._lock:
            # Gather vision images for this turn
            vision_images = [f.image for f in self._vision_buffer]
            self._vision_buffer.clear()

            # Build system prompt (static for caching)
            system_prompt = self._prompt_builder.build()

            # Prepend dynamic context (emojis, participants) to user message
            if dynamic_context:
                text = f"[Context: {dynamic_context}]\n{text}"

            # Build messages list
            messages: list[LLMMessage] = [
                LLMMessage(role="system", content=system_prompt)
            ]
            if self._config.memory.conversation_window > 0:
                messages.extend(self._history[-(self._config.memory.conversation_window * 2):])

            # Current user turn
            user_msg = LLMMessage(role="user", content=text, images=vision_images + images)
            messages.append(user_msg)

            # Build tool list and betas from registry
            tools = self._registry.build(mode=tool_mode)
            betas = self._registry.beta_headers()

            max_continues = getattr(self._config.memory, "max_continues", MAX_CONTINUE_DEFAULT)
            all_responses: list[str] = []
            continue_count = 0
            max_iterations = max_continues + 5  # hard safety cap

            # ---- Turn loop (tool results + continue) ----
            for _iteration in range(max_iterations):
                logger.debug("Sending %d messages to LLM with %d tools", len(messages), len(tools))
                llm_response = await self._claude.generate(messages=messages, tools=tools, betas=betas)
                logger.debug("LLM response text: %s", llm_response.text)
                logger.debug("LLM tool calls: %s", llm_response.tool_calls)

                # Process tool calls and collect results
                expressions: list[dict] = []
                actions: list[dict] = []
                tool_results: list[dict] = []
                wants_continue = False

                for tool_call in llm_response.tool_calls:
                    # Skip server-side tools — results are already in the response
                    if self._dispatcher.is_server_side(tool_call.name):
                        continue

                    if self._dispatcher.is_continue(tool_call.name):
                        wants_continue = True
                        tool_results.append({"id": tool_call.id, "content": "ok"})
                    elif self._dispatcher.is_expression(tool_call.name):
                        # Parse expression args and emit event
                        expr_name = tool_call.arguments.get("name", "neutral")
                        try:
                            intensity = float(tool_call.arguments.get("intensity", 0.7))
                        except (ValueError, TypeError):
                            logger.warning(
                                "Invalid expression intensity %r for tool %s; defaulting to 0.7",
                                tool_call.arguments.get("intensity"),
                                tool_call.name,
                            )
                            intensity = 0.7
                        expressions.append({"name": expr_name, "intensity": intensity})
                        await self._bus.publish(
                            ExpressionChange(name=expr_name, intensity=intensity)
                        )
                        try:
                            result = await self._dispatcher.dispatch(tool_call)
                        except Exception:
                            logger.exception("Tool executor raised for %s (id=%s)", tool_call.name, tool_call.id)
                            result = f"Error: tool '{tool_call.name}' raised an exception"
                        tool_results.append({"id": tool_call.id, "content": _tool_content(result)})
                    else:
                        try:
                            result = await self._dispatcher.dispatch(tool_call)
                        except Exception:
                            logger.exception("Tool executor raised for %s (id=%s)", tool_call.name, tool_call.id)
                            result = f"Error: tool '{tool_call.name}' raised an exception"
                        tool_results.append({"id": tool_call.id, "content": _tool_content(result)})

                # Collect response text
                if llm_response.text:
                    all_responses.append(llm_response.text)

                # Emit LLMResponse event for this turn's text
                if llm_response.text:
                    await self._bus.publish(
                        LLMResponseEvent(
                            text=llm_response.text,
                            expressions=expressions,
                            actions=actions,
                            mood="neutral",
                        )
                    )

                # Server-side tool loop paused — re-send to continue
                if llm_response.stop_reason == "pause_turn":
                    if llm_response.tool_calls:
                        messages.append(
                            LLMMessage(
                                role="assistant",
                                content=llm_response.text,
                                tool_calls=[
                                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                                    for tc in llm_response.tool_calls
                                ],
                            )
                        )
                        if tool_results:
                            messages.append(
                                LLMMessage(role="user", content="", tool_results=tool_results)
                            )
                    else:
                        messages.append(
                            LLMMessage(role="assistant", content=llm_response.text)
                        )
                    continue

                # No tool calls at all — conversation is done
                if not tool_results:
                    messages.append(LLMMessage(role="assistant", content=llm_response.text))
                    break

                # Feed tool results back to LLM for the next iteration
                messages.append(
                    LLMMessage(
                        role="assistant",
                        content=llm_response.text,
                        tool_calls=[
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in llm_response.tool_calls
                        ],
                    )
                )
                messages.append(
                    LLMMessage(role="user", content="", tool_results=tool_results)
                )

                # Enforce continue cap
                if wants_continue:
                    continue_count += 1
                    if continue_count > max_continues:
                        logger.debug("Continue cap reached (%d)", max_continues)
                        break

            else:
                # Loop exhausted without breaking — make a final tool-free call
                logger.debug("Tool loop exhausted after %d iterations, making final call", max_iterations)
                llm_response = await self._claude.generate(messages=messages, tools=None, betas=betas)
                if llm_response.text:
                    all_responses.append(llm_response.text)
                    await self._bus.publish(
                        LLMResponseEvent(
                            text=llm_response.text,
                            expressions=[],
                            actions=[],
                            mood="neutral",
                        )
                    )

            # ---- Persist to history ----
            # Store text-only version in history (images are one-time context, not worth replaying)
            self._history.append(LLMMessage(role="user", content=user_msg.content if isinstance(user_msg.content, str) else str(user_msg.content)))
            combined_text = "\n\n".join(all_responses)
            self._history.append(
                LLMMessage(role="assistant", content=combined_text)
            )
            # Trim history (conversation_window counts message pairs)
            max_entries = self._config.memory.conversation_window * 2
            if max_entries > 0 and len(self._history) > max_entries:
                self._history = self._history[-max_entries:]

            return all_responses
