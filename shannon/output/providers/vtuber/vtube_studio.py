"""VTubeStudioProvider — controls a VTuber avatar via the VTube Studio WebSocket API."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from shannon.output.providers.vtuber.base import VTuberProvider

_PLUGIN_NAME = "Shannon"
_PLUGIN_DEVELOPER = "Shannon AI"

logger = logging.getLogger(__name__)


class VTubeStudioProvider(VTuberProvider):
    """Connects to VTube Studio via its WebSocket API and drives expressions/mouth."""

    def __init__(
        self,
        url: str = "ws://localhost:8001",
        plugin_name: str = _PLUGIN_NAME,
        plugin_developer: str = _PLUGIN_DEVELOPER,
        auth_token: str | None = None,
    ) -> None:
        self._url = url
        self._plugin_name = plugin_name
        self._plugin_developer = plugin_developer
        self._auth_token = auth_token
        self._ws: Any = None  # websockets connection

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the WebSocket connection and authenticate with VTube Studio."""
        try:
            import websockets  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "websockets is not installed. "
                "Install it with: pip install websockets"
            ) from exc

        self._ws = await websockets.connect(self._url)
        await self._authenticate()

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    # ------------------------------------------------------------------
    # VTuberProvider interface
    # ------------------------------------------------------------------

    async def set_expression(self, name: str, intensity: float) -> None:
        """Activate a hotkey by expression name via VTS ExpressionActivationRequest."""
        await self._send(
            "ExpressionActivationRequest",
            {
                "expressionFile": f"{name}.exp3.json",
                "active": True,
            },
        )

    async def start_speaking(self, phonemes: list[str] | None = None) -> None:
        """Open the mouth via an InjectParameterDataRequest for MouthOpen."""
        await self._inject_mouth(value=0.8)

    async def stop_speaking(self) -> None:
        """Close the mouth via an InjectParameterDataRequest for MouthOpen."""
        await self._inject_mouth(value=0.0)

    async def set_idle_animation(self, name: str) -> None:
        """Trigger an idle animation hotkey by name."""
        await self._send(
            "HotkeyTriggerRequest",
            {"hotkeyID": name},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _authenticate(self) -> None:
        """Perform the VTube Studio plugin authentication handshake."""
        if self._auth_token:
            # Already have a token — just authenticate
            await self._send(
                "AuthenticationRequest",
                {
                    "pluginName": self._plugin_name,
                    "pluginDeveloper": self._plugin_developer,
                    "authenticationToken": self._auth_token,
                },
            )
            resp = await self._recv()
            if resp.get("data", {}).get("authenticated"):
                return
            # Token rejected — fall through to request a new one

        # Request a fresh authentication token
        await self._send(
            "AuthenticationTokenRequest",
            {
                "pluginName": self._plugin_name,
                "pluginDeveloper": self._plugin_developer,
            },
        )
        resp = await self._recv()
        token = resp.get("data", {}).get("authenticationToken", "")
        if token:
            self._auth_token = token
            # Now authenticate with the new token
            await self._send(
                "AuthenticationRequest",
                {
                    "pluginName": self._plugin_name,
                    "pluginDeveloper": self._plugin_developer,
                    "authenticationToken": self._auth_token,
                },
            )
            resp = await self._recv()
            if not resp.get("data", {}).get("authenticated"):
                logger.warning("VTube Studio authentication failed")
                await self.disconnect()
                return

    async def _inject_mouth(self, value: float) -> None:
        """Inject a MouthOpen parameter value."""
        await self._send(
            "InjectParameterDataRequest",
            {
                "faceFound": False,
                "mode": "set",
                "parameterValues": [
                    {"id": "MouthOpen", "value": value},
                ],
            },
        )

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
            logger.warning("VTube Studio connection lost")
            self._ws = None

    async def _recv(self) -> dict[str, Any]:
        """Receive and deserialise the next VTS API message."""
        if self._ws is None:
            raise RuntimeError("Not connected")
        raw = await self._ws.recv()
        return json.loads(raw)
