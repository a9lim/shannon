"""Shannon app entry point — wires all modules together and starts the event loop."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shannon.config import ShannonConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="shannon",
        description="Shannon — an AI assistant with memory, vision, and actions.",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config YAML file (default: config.yaml)",
    )
    parser.add_argument(
        "--dangerously-skip-permissions",
        action="store_true",
        default=False,
        help="Skip all action approval prompts (sets all approvals to 'allow')",
    )
    parser.add_argument(
        "--speech",
        action="store_true",
        default=False,
        help="Enable speech mode (STT input + TTS output)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable debug logging",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Async run
# ---------------------------------------------------------------------------

async def run(config: "ShannonConfig", speech_mode: bool = False) -> None:
    """Wire up all modules and run Shannon."""
    from shannon.bus import EventBus

    bus = EventBus()

    # ------------------------------------------------------------------
    # LLM
    # ------------------------------------------------------------------
    from shannon.brain.claude import ClaudeClient

    claude = ClaudeClient(config.llm)

    # ------------------------------------------------------------------
    # Tool executors
    # ------------------------------------------------------------------
    from shannon.tools.bash_executor import BashExecutor
    from shannon.tools.text_editor_executor import TextEditorExecutor

    bash_executor = BashExecutor(config.tools.bash)
    text_editor_executor = TextEditorExecutor(config.tools.text_editor)

    # Computer use (optional — needs pyautogui)
    computer_executor = None
    if config.tools.computer_use.enabled:
        try:
            from shannon.computer.executor import ComputerUseExecutor
            computer_executor = ComputerUseExecutor(config.tools.computer_use)
        except ImportError:
            logger.warning("pyautogui not installed — computer use disabled")

    # Memory backend
    from shannon.tools.memory_backend import MemoryBackend

    memory_backend = MemoryBackend(config.memory.dir)

    # ------------------------------------------------------------------
    # Dispatcher and registry
    # ------------------------------------------------------------------
    from shannon.brain.tool_dispatch import ToolDispatcher
    from shannon.brain.tool_registry import ToolRegistry

    dispatcher = ToolDispatcher(
        computer_executor=computer_executor,
        bash_executor=bash_executor,
        text_editor_executor=text_editor_executor,
        memory_backend=memory_backend,
        tools_config=config.tools,
        bus=bus,
    )
    registry = ToolRegistry(config)

    # CLI confirmation handler — prompts via stdin when a tool needs approval
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

    # ------------------------------------------------------------------
    # Brain
    # ------------------------------------------------------------------
    from shannon.brain.brain import Brain

    brain = Brain(bus=bus, claude=claude, dispatcher=dispatcher, registry=registry, config=config)
    await brain.start()

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    from shannon.input.manager import InputManager
    from shannon.input.providers.text import TextInputProvider

    text_provider = TextInputProvider()
    stt_provider = None

    if speech_mode:
        try:
            from shannon.input.providers.whisper import WhisperProvider
            stt_cfg = config.stt
            stt_provider = WhisperProvider(
                model_size=stt_cfg.model,
                device=stt_cfg.device,
            )
        except ImportError:
            logger.warning(
                "faster-whisper not installed; speech input unavailable. "
                "Install with: pip install faster-whisper"
            )

    input_manager = InputManager(
        bus=bus,
        text_provider=text_provider,
        stt_provider=stt_provider,
    )
    input_manager.set_speech_mode(speech_mode)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    from shannon.output.manager import OutputManager

    tts_provider = None
    vtuber_provider = None

    if speech_mode:
        tts_type = config.tts.type
        if tts_type == "piper":
            try:
                from shannon.output.providers.tts.piper import PiperProvider
                tts_provider = PiperProvider(model_path=config.tts.model)
            except ImportError:
                logger.warning(
                    "piper-tts not installed; speech output unavailable. "
                    "Install with: pip install piper-tts"
                )

    vtuber_cfg = config.vtuber
    if vtuber_cfg.type == "vtube_studio":
        try:
            import websockets  # noqa: F401 — check availability
            from shannon.output.providers.vtuber.vtube_studio import VTubeStudioProvider
            vtuber_provider = VTubeStudioProvider(
                url=f"ws://{vtuber_cfg.host}:{vtuber_cfg.port}",
                auth_token=vtuber_cfg.auth_token or None,
            )
        except ImportError:
            logger.warning(
                "websockets not installed; VTuber integration unavailable. "
                "Install with: pip install websockets"
            )

    if vtuber_provider is not None:
        try:
            await vtuber_provider.connect()
        except Exception:
            logger.warning("Could not connect to VTube Studio — expressions disabled")
            vtuber_provider = None

    output_manager = OutputManager(
        bus=bus,
        tts_provider=tts_provider,
        vtuber_provider=vtuber_provider,
        speech_output=speech_mode and tts_provider is not None,
    )
    output_manager.start()

    # ------------------------------------------------------------------
    # Vision
    # ------------------------------------------------------------------
    from shannon.vision.manager import VisionManager

    vision_providers = []
    vision_cfg = config.vision

    if vision_cfg.screen:
        try:
            import mss  # noqa: F401 — check availability
            from shannon.vision.providers.screen import ScreenCapture
            vision_providers.append(ScreenCapture(
                max_width=vision_cfg.max_width,
                max_height=vision_cfg.max_height,
            ))
        except ImportError:
            logger.warning(
                "mss not installed; screen capture unavailable. "
                "Install with: pip install mss"
            )

    if vision_cfg.webcam:
        try:
            import cv2  # noqa: F401 — check availability
            from shannon.vision.providers.webcam import WebcamCapture
            vision_providers.append(WebcamCapture())
        except ImportError:
            logger.warning(
                "opencv-python not installed; webcam capture unavailable. "
                "Install with: pip install opencv-python"
            )

    vision_manager = VisionManager(
        bus=bus,
        providers=vision_providers,
        interval_seconds=vision_cfg.interval_seconds,
    )

    # ------------------------------------------------------------------
    # Autonomy
    # ------------------------------------------------------------------
    from shannon.autonomy.loop import AutonomyLoop

    autonomy_loop = AutonomyLoop(bus=bus, config=config)

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------
    from shannon.messaging.manager import MessagingManager

    messaging_providers = []
    msg_cfg = config.messaging

    if msg_cfg.enabled and msg_cfg.type == "discord" and msg_cfg.token:
        try:
            import discord  # noqa: F401 — check availability
            from shannon.messaging.providers.discord import DiscordProvider
            messaging_providers.append(DiscordProvider(
                token=msg_cfg.token,
                conversation_expiry=msg_cfg.conversation_expiry,
            ))
        except ImportError:
            logger.warning(
                "discord.py not installed; Discord integration unavailable. "
                "Install with: pip install discord.py"
            )

    messaging_manager = MessagingManager(bus=bus, providers=messaging_providers, config=msg_cfg)
    await messaging_manager.start()

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------
    name = config.personality.name
    mode_label = "speech" if speech_mode else "text"
    print(f"{name} is online. Mode: {mode_label}. Press Ctrl+C to exit.")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    tasks = [
        asyncio.create_task(input_manager.run_text_loop()),
        asyncio.create_task(autonomy_loop.run()),
    ]

    if vision_providers:
        tasks.append(asyncio.create_task(vision_manager.run()))

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        # Cancel all background tasks
        for task in tasks:
            task.cancel()
        # Wait for cancellations to propagate
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse args, configure logging, load config, and run."""
    args = parse_args(sys.argv[1:])

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from shannon.config import load_config
    config = load_config(args.config)

    if args.dangerously_skip_permissions:
        config.apply_dangerously_skip_permissions()

    try:
        asyncio.run(run(config=config, speech_mode=args.speech))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
