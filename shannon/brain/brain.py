"""Brain manager — central intelligence for Shannon."""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from typing import TYPE_CHECKING

from shannon.brain.prompt import PromptBuilder
from shannon.brain.reactions import extract_reactions
from shannon.brain.types import GenerationRequest, LLMMessage, LLMToolCall, LLMResponse
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
    VoiceInput,
    VoiceOutput,
)

if TYPE_CHECKING:
    from shannon.brain.claude import ClaudeClient
    from shannon.brain.tool_dispatch import ToolDispatcher
    from shannon.brain.tool_registry import ToolRegistry
    from shannon.output.providers.tts.base import TTSProvider

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
        tts: "TTSProvider | None" = None,
    ) -> None:
        self._bus = bus
        self._claude = claude
        self._dispatcher = dispatcher
        self._registry = registry
        self._config = config
        self._tts = tts
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
        self._bus.subscribe(VoiceInput, self._on_voice_input)
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
        logger.info("UserInput: %s", event.text[:120])
        await self._process_input(GenerationRequest(text=event.text))

    async def _on_chat_message(self, event: ChatMessage) -> None:
        logger.info("ChatMessage from %s/%s: %s", event.platform, event.channel, event.text[:120])

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
        if event.custom_emojis and self._config.messaging.reaction_probability > 0:
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

        request = GenerationRequest(
            text=text,
            images=images,
            dynamic_context=dynamic_context,
            tool_mode="chat",
            channel_id=event.channel,
            participants=event.participants,
        )
        responses = await self._process_input(request)
        for i, response_text in enumerate(responses):
            clean_text, reactions = extract_reactions(response_text)
            if clean_text or reactions:
                await self._bus.publish(
                    ChatResponse(
                        text=clean_text,
                        platform=event.platform,
                        channel=event.channel,
                        # NOTE: only the first response in a continue chain gets reply_to.
                        # Reactions on follow-up messages are dropped (known limitation;
                        # fixing requires send_message to return message IDs).
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

    async def _on_voice_input(self, event: VoiceInput) -> None:
        """Handle transcribed voice channel speech."""
        logger.info("VoiceInput from channel %s: %s", event.channel, event.text[:120])

        prob = self._config.messaging.voice.voice_reply_probability
        if prob < 1.0 and random.random() > prob:
            logger.debug("Skipping voice input (probability check)")
            return

        suffix_parts: list[str] = []
        if event.speakers:
            names = list(event.speakers.values())
            suffix_parts.append(f"Voice channel participants: {', '.join(names)}")
        dynamic_context = "\n".join(suffix_parts)

        request = GenerationRequest(
            text=event.text,
            dynamic_context=dynamic_context,
            tool_mode="chat",
            channel_id=event.channel,
            participants=event.speakers,
        )
        responses = await self._process_input(request)

        # Synthesize TTS audio for voice channel playback
        if self._tts is not None and responses and any(r.strip() for r in responses):
            full_text = "\n".join(r for r in responses if r.strip())
            try:
                chunk = await self._tts.synthesize(full_text)
                await self._bus.publish(VoiceOutput(
                    audio=chunk,
                    channel=event.channel,
                ))
            except Exception:
                logger.exception("Failed to synthesize voice response")

    async def _on_autonomous_trigger(self, event: AutonomousTrigger) -> None:
        await self._process_input(GenerationRequest(
            text=f"[Autonomous trigger: {event.reason}] {event.context}",
            tool_mode="chat",
        ))

    async def _on_vision_frame(self, event: VisionFrame) -> None:
        self._vision_buffer.append(event)
        if len(self._vision_buffer) > 1:
            self._vision_buffer = self._vision_buffer[-1:]

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def _process_input(self, request: GenerationRequest) -> list[str]:
        """Build context, call LLM, process tool calls, emit events.

        Returns a list of response texts. Multiple entries when the LLM uses
        the ``continue`` tool to send follow-up messages.
        """
        if self._prompt_builder is None:
            raise RuntimeError("Brain.start() must be called before processing input")

        async with self._lock:
            # Gather vision images for this turn
            vision_images = [f.image for f in self._vision_buffer]
            self._vision_buffer.clear()

            # Build system prompt (static for caching)
            system_prompt = self._prompt_builder.build()

            # Prepend dynamic context (emojis, participants) to user message
            text = request.text
            if request.dynamic_context:
                text = f"[Context: {request.dynamic_context}]\n{text}"

            # Build messages list
            messages: list[LLMMessage] = [
                LLMMessage(role="system", content=system_prompt)
            ]
            max_history = self._config.memory.max_session_messages
            if max_history > 0:
                # Copy to prevent mutation of stored history during the tool loop
                messages.extend(
                    LLMMessage(
                        role=m.role,
                        content=m.content if isinstance(m.content, str) else list(m.content),
                        images=list(m.images),
                        tool_calls=list(m.tool_calls),
                        tool_results=list(m.tool_results),
                    )
                    for m in self._history[-max_history:]
                )

            # Current user turn
            user_msg = LLMMessage(role="user", content=text, images=vision_images + list(request.images))
            messages.append(user_msg)

            # Build tool list and betas from registry
            tools = self._registry.build(mode=request.tool_mode)
            betas = self._registry.beta_headers()

            # Set conversation context on dispatcher for this turn
            self._dispatcher.set_context(request.channel_id, request.participants)

            max_continues = getattr(self._config.memory, "max_continues", MAX_CONTINUE_DEFAULT)
            all_responses: list[str] = []
            continue_count = 0
            max_iterations = max_continues + 5  # hard safety cap

            # ---- Turn loop (tool results + continue) ----
            for _iteration in range(max_iterations):
                logger.debug("Sending %d messages to LLM (iteration %d)", len(messages), _iteration)
                llm_response = await self._claude.generate(messages=messages, tools=tools, betas=betas)

                # Strip images after first send to avoid re-transmitting on tool loops
                if _iteration == 0:
                    for msg in messages:
                        if msg.images:
                            msg.images = []

                if llm_response.tool_calls:
                    tool_names = [tc.name for tc in llm_response.tool_calls]
                    logger.info("LLM requested tools: %s", ", ".join(tool_names))
                logger.debug("LLM response text: %s", llm_response.text[:200] if llm_response.text else "(empty)")

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
                        continue
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
                        tool_results.append({"id": tool_call.id, "content": "ok"})
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
                    logger.info("Response text (%d chars): %s", len(llm_response.text), llm_response.text[:200])
                elif llm_response.stop_reason == "end_turn":
                    logger.warning("end_turn with empty text — output may be all thinking tokens")

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
                    # Only include client-side tool_use blocks — server-side
                    # ones are handled by the API and must not appear without
                    # a matching tool_result.
                    client_calls = [
                        tc for tc in llm_response.tool_calls
                        if not self._dispatcher.is_server_side(tc.name)
                    ]
                    if client_calls:
                        messages.append(
                            LLMMessage(
                                role="assistant",
                                content=llm_response.text,
                                tool_calls=[
                                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                                    for tc in client_calls
                                ],
                            )
                        )
                        if tool_results:
                            messages.append(
                                LLMMessage(role="user", content="", tool_results=tool_results)
                            )
                    elif llm_response.text:
                        messages.append(
                            LLMMessage(role="assistant", content=llm_response.text)
                        )
                    continue

                # No tool calls at all — conversation is done
                if not tool_results:
                    messages.append(LLMMessage(role="assistant", content=llm_response.text))
                    break

                # Feed tool results back to LLM for the next iteration.
                # Only include client-side tool_use blocks — server-side
                # ones are handled by the API and must not appear without
                # a matching tool_result.
                client_calls = [
                    tc for tc in llm_response.tool_calls
                    if not self._dispatcher.is_server_side(tc.name)
                ]
                messages.append(
                    LLMMessage(
                        role="assistant",
                        content=llm_response.text,
                        tool_calls=[
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in client_calls
                        ],
                    )
                )
                messages.append(
                    LLMMessage(role="user", content="", tool_results=tool_results)
                )

                # Enforce continue cap
                if wants_continue:
                    continue_count += 1
                    if continue_count >= max_continues:
                        logger.info("Continue cap reached (%d/%d)", continue_count, max_continues)
                        break

            else:
                # Loop exhausted without breaking — make a final tool-free call
                logger.warning("Tool loop exhausted after %d iterations, making final tool-free call", max_iterations)
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
            # Store text-only copies in history (images are one-time context)
            combined_text = "\n\n".join(all_responses)
            if combined_text:
                # Store original text without [Context: ...] prefix
                history_content = user_msg.content if isinstance(user_msg.content, str) else str(user_msg.content)
                if history_content.startswith("[Context: ") and "]\n" in history_content:
                    history_content = history_content[history_content.index("]\n") + 2:]
                self._history.append(LLMMessage(role="user", content=history_content))
                self._history.append(LLMMessage(
                    role="assistant",
                    content=combined_text,
                ))
            # Trim history or clear for stateless mode
            if max_history > 0 and len(self._history) > max_history:
                self._history = self._history[-max_history:]
            elif max_history == 0:
                self._history.clear()

            if not all_responses:
                logger.warning("_process_input completed with no response text")
            else:
                logger.info("_process_input completed with %d response(s)", len(all_responses))
            return all_responses
