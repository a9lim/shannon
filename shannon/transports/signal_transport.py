"""Signal transport via signal-cli (subprocess) or signal-cli-rest-api (HTTP)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from shannon.config import ChunkerConfig, SignalConfig
from shannon.core.bus import Event, EventBus, EventType, MessageIncoming, MessageOutgoing
from shannon.core.chunker import chunk_message
from shannon.transports.base import Transport
from shannon.utils.logging import get_logger

log = get_logger(__name__)


class SignalTransport(Transport):
    def __init__(
        self,
        config: SignalConfig,
        bus: EventBus,
        chunker_config: ChunkerConfig | None = None,
    ) -> None:
        super().__init__(bus)
        self._config = config
        self._chunker_config = chunker_config or ChunkerConfig()
        self._running = False
        self._receive_task: asyncio.Task[None] | None = None
        self._http_client: httpx.AsyncClient | None = None

    @property
    def platform_name(self) -> str:
        return "signal"

    async def start(self) -> None:
        self.bus.subscribe(EventType.MESSAGE_OUTGOING, self._handle_outgoing)
        self._running = True

        if self._config.mode == "rest":
            self._http_client = httpx.AsyncClient(
                base_url=self._config.rest_api_url.rstrip("/"),
                timeout=30,
            )
            self._receive_task = asyncio.create_task(
                self._poll_rest_api(), name="signal-rest-poller"
            )
        else:
            self._receive_task = asyncio.create_task(
                self._poll_signal_cli(), name="signal-cli-poller"
            )

        log.info("signal_transport_started", mode=self._config.mode)

    async def stop(self) -> None:
        self._running = False
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._http_client:
            await self._http_client.aclose()
        log.info("signal_transport_stopped")

    # ------------------------------------------------------------------
    # signal-cli subprocess mode
    # ------------------------------------------------------------------

    async def _poll_signal_cli(self) -> None:
        """Poll for messages using `signal-cli receive --json`."""
        while self._running:
            try:
                proc = await asyncio.create_subprocess_exec(
                    self._config.signal_cli_path,
                    "-a", self._config.phone_number,
                    "receive", "--json", "--timeout", "5",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                assert proc.stdout is not None

                async for line in proc.stdout:
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if not decoded:
                        continue
                    try:
                        envelope = json.loads(decoded)
                        await self._process_cli_envelope(envelope)
                    except json.JSONDecodeError:
                        log.debug("signal_cli_parse_error", line=decoded[:200])

                await proc.wait()
            except FileNotFoundError:
                log.error("signal_cli_not_found", path=self._config.signal_cli_path)
                await asyncio.sleep(30)
            except Exception:
                log.exception("signal_cli_poll_error")
                await asyncio.sleep(5)

    async def _process_cli_envelope(self, envelope: dict[str, Any]) -> None:
        env = envelope.get("envelope", envelope)
        data_msg = env.get("dataMessage")
        if not data_msg:
            return

        sender = env.get("source", env.get("sourceNumber", ""))
        content = data_msg.get("message", "")
        group_info = data_msg.get("groupInfo")
        group_id = group_info.get("groupId", "") if group_info else ""

        if not content:
            return

        attachments = [
            {"filename": a.get("filename", ""), "contentType": a.get("contentType", "")}
            for a in data_msg.get("attachments", [])
        ]

        channel = group_id if group_id else sender
        event = MessageIncoming(data={
            "platform": "signal",
            "channel": channel,
            "user_id": sender,
            "user_name": sender,
            "content": content,
            "attachments": attachments,
            "group_id": group_id,
        })
        await self.bus.publish(event)

    async def _send_signal_cli(
        self, recipient: str, message: str, group_id: str = ""
    ) -> None:
        args = [
            self._config.signal_cli_path,
            "-a", self._config.phone_number,
            "send", "-m", message,
        ]
        if group_id:
            args.extend(["--group-id", group_id])
        else:
            args.append(recipient)

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.error("signal_cli_send_error", stderr=stderr.decode()[:200])

    # ------------------------------------------------------------------
    # signal-cli-rest-api HTTP mode
    # ------------------------------------------------------------------

    async def _poll_rest_api(self) -> None:
        """Poll the REST API for incoming messages."""
        number = self._config.phone_number
        while self._running:
            try:
                assert self._http_client is not None
                resp = await self._http_client.get(f"/v1/receive/{number}")
                if resp.status_code == 200:
                    messages = resp.json()
                    for msg_envelope in messages:
                        await self._process_rest_envelope(msg_envelope)
            except httpx.ConnectError:
                log.warning("signal_rest_api_unavailable")
                await asyncio.sleep(10)
            except Exception:
                log.exception("signal_rest_poll_error")
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(1)

    async def _process_rest_envelope(self, envelope: dict[str, Any]) -> None:
        env = envelope.get("envelope", envelope)
        data_msg = env.get("dataMessage")
        if not data_msg:
            return

        sender = env.get("source", env.get("sourceNumber", ""))
        content = data_msg.get("message", "")
        group_info = data_msg.get("groupInfo")
        group_id = group_info.get("groupId", "") if group_info else ""

        if not content:
            return

        attachments = [
            {"filename": a.get("filename", ""), "contentType": a.get("contentType", "")}
            for a in data_msg.get("attachments", [])
        ]

        channel = group_id if group_id else sender
        event = MessageIncoming(data={
            "platform": "signal",
            "channel": channel,
            "user_id": sender,
            "user_name": sender,
            "content": content,
            "attachments": attachments,
            "group_id": group_id,
        })
        await self.bus.publish(event)

    async def _send_rest_api(
        self, recipient: str, message: str, group_id: str = ""
    ) -> None:
        assert self._http_client is not None
        body: dict[str, Any] = {
            "message": message,
            "number": self._config.phone_number,
        }
        if group_id:
            body["recipients"] = [group_id]
        else:
            body["recipients"] = [recipient]

        resp = await self._http_client.post("/v2/send", json=body)
        if resp.status_code not in (200, 201):
            log.error("signal_rest_send_error", status=resp.status_code, body=resp.text[:200])

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def send_message(
        self,
        channel: str,
        content: str,
        *,
        reply_to: str | None = None,
        embed: dict[str, Any] | None = None,
        files: list[str] | None = None,
    ) -> None:
        # Determine if channel is a group or individual
        # Group IDs are base64-encoded, phone numbers start with +
        is_group = not channel.startswith("+")

        chunks = chunk_message(
            content,
            limit=self._chunker_config.signal_limit,
            config=self._chunker_config,
        )

        for chunk_text in chunks:
            if self._config.mode == "rest":
                await self._send_rest_api(
                    channel, chunk_text, group_id=channel if is_group else ""
                )
            else:
                await self._send_signal_cli(
                    channel, chunk_text, group_id=channel if is_group else ""
                )
            # Typing delay between chunks
            if len(chunks) > 1:
                delay = len(chunk_text) * self._chunker_config.typing_delay_ms_per_char / 1000
                await asyncio.sleep(min(delay, 3.0))

    async def _handle_outgoing(self, event: Event) -> None:
        if event.data.get("platform") != "signal":
            return

        channel = event.data["channel"]
        content = event.data.get("content", "")

        await self.send_message(channel, content)
