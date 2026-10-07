"""Client for a Tibber bridge's local /ws meter data stream.

Kept free of Home Assistant imports, so it can be exercised on its own.
"""

import asyncio
import base64
from collections.abc import Callable
from dataclasses import dataclass
import json
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

WS_PATH = "/ws"
PARAMS_PATH = "/params.json"
STATUS_PATH = "/status.json"
# Basic auth: the bridge checks the password only, any user name works
AUTH_USER = "x"

BACKOFF_MIN = 1.0
BACKOFF_MAX = 60.0
# A connection that lasted this long resets the backoff
STABLE_AFTER = 30.0
HEARTBEAT = 30.0
REQUEST_TIMEOUT = 10.0


class TibberPulseError(Exception):
    """Base error talking to the bridge."""


class TibberPulseAuthError(TibberPulseError):
    """The bridge refused the password."""


class TibberPulseConnectionError(TibberPulseError):
    """The bridge could not be reached."""


@dataclass(frozen=True, slots=True)
class Reading:
    """One decoded meter reading from the stream."""

    euid: str
    data: dict[str, Any]


def auth_header(password: str) -> dict[str, str]:
    """Return the Authorization header for the bridge's web password."""
    token = base64.b64encode(f"{AUTH_USER}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def parse_message(message: str | bytes) -> Reading | None:
    """Parse one /ws message into a reading, None for anything else.

    A message is a header, <device:<16 hex euid> topic:"<topic>">, followed by
    the payload; for the reading topic, a JSON object.
    """
    if isinstance(message, bytes):
        try:
            message = message.decode()
        except UnicodeDecodeError:
            return None
    end = message.find(">")
    if not message.startswith("<device:") or end < 0:
        return None
    fields = dict(part.split(":", 1) for part in message[1:end].split() if ":" in part)
    euid = fields.get("device", "").lower()
    topic = fields.get("topic", "").strip('"')
    if topic != "reading" or len(euid) != 16:
        return None
    try:
        data = json.loads(message[end + 1 :])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    return Reading(euid=euid, data=data)


class TibberPulseClient:
    """Streams decoded readings from a bridge, reconnecting until stopped."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        password: str,
        on_reading: Callable[[Reading], None],
        on_connection: Callable[[bool], None] | None = None,
        on_auth_failed: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._host = host
        self._password = password
        self._on_reading = on_reading
        self._on_connection = on_connection
        self._on_auth_failed = on_auth_failed
        self.connected = False

    @property
    def base_url(self) -> str:
        """Return the bridge's HTTP base URL."""
        return f"http://{self._host}"

    async def async_validate(self) -> None:
        """Open /ws once to check that the bridge answers and accepts the password."""
        ws = await self._connect()
        await ws.close()

    async def async_get_device_id(self) -> str | None:
        """Return the bridge's device id (its MQTT client id), or None."""
        params = await self._get_json(PARAMS_PATH)
        if not isinstance(params, list):
            return None
        for param in params:
            if isinstance(param, dict) and param.get("name") == "mqtt_client_id":
                # A string param's value is the string itself
                value = param.get("value")
                if isinstance(value, list):
                    value = value[0] if value else None
                return value.lower() if isinstance(value, str) and value else None
        return None

    async def async_get_status(self) -> dict[str, Any] | None:
        """Return the bridge's status.json (firmware versions and more), or None."""
        status = await self._get_json(STATUS_PATH)
        return status if isinstance(status, dict) else None

    async def run(self) -> None:
        """Stream readings until cancelled or the password is refused."""
        backoff = BACKOFF_MIN
        loop = asyncio.get_running_loop()
        while True:
            started = loop.time()
            try:
                ws = await self._connect()
            except TibberPulseAuthError:
                _LOGGER.error("Bridge %s refused the password", self._host)
                if self._on_auth_failed:
                    self._on_auth_failed()
                return
            except TibberPulseConnectionError as err:
                _LOGGER.debug("Cannot connect to %s: %s", self._host, err)
            else:
                try:
                    await self._receive(ws)
                finally:
                    await ws.close()
                    self._set_connected(False)
            if loop.time() - started >= STABLE_AFTER:
                backoff = BACKOFF_MIN
            _LOGGER.debug("Reconnecting to %s in %.0f s", self._host, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)

    async def _connect(self) -> aiohttp.ClientWebSocketResponse:
        try:
            return await self._session.ws_connect(
                f"{self.base_url}{WS_PATH}",
                params={"kind": "reading"},
                headers=auth_header(self._password),
                heartbeat=HEARTBEAT,
            )
        except aiohttp.WSServerHandshakeError as err:
            if err.status == 401:
                raise TibberPulseAuthError from err
            raise TibberPulseConnectionError(f"handshake failed: {err.status}") from err
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            raise TibberPulseConnectionError(str(err)) from err

    async def _receive(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        self._set_connected(True)
        async for msg in ws:
            if msg.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                reading = parse_message(msg.data)
                if reading is not None:
                    self._on_reading(reading)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                _LOGGER.debug("Websocket error from %s: %s", self._host, ws.exception())
                break
        # The bridge serves a limited number of clients: a closed socket may mean
        # another one took this one's place
        _LOGGER.debug("Websocket to %s closed (code %s)", self._host, ws.close_code)

    async def _get_json(self, path: str) -> Any:
        try:
            async with self._session.get(
                f"{self.base_url}{path}",
                headers=auth_header(self._password),
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                status = resp.status
                body = await resp.json(content_type=None) if status == 200 else None
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as err:
            _LOGGER.debug("GET %s from %s failed: %s", path, self._host, err)
            return None
        if status == 401:
            raise TibberPulseAuthError
        return body

    def _set_connected(self, connected: bool) -> None:
        if connected != self.connected:
            self.connected = connected
            if self._on_connection:
                self._on_connection(connected)
