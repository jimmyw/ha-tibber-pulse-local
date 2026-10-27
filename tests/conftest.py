"""Fixtures for Tibber Pulse (local) tests: a fake bridge on localhost."""

import asyncio
import base64
from collections.abc import AsyncGenerator
import copy
import json
from typing import Any
from unittest.mock import patch

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tibber_pulse_local.const import DOMAIN
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant

PASSWORD = "TEST-PASS"
# API tokens: one opening /ws only, one opening everything like the password
STREAM_TOKEN = "c3RyZWFtLXRva2VuLWZvci10"
FULL_TOKEN = "ZnVsbC10b2tlbi1mb3ItdGVz"
DEVICE_ID = "0123456789ab"
EUID = "00112233445566aa"

# As an Addax AD13A sends it: voltage, current and energy, no power
READING: dict[str, Any] = {
    "eui": EUID,
    "model": "TFD01",
    "decoded_as": "obis_ascii",
    "meter_id": None,
    "meter_type": "Unknown P1",
    "version_id": None,
    "meter_brand": None,
    "meter_time_ms": None,
    "p_import_w": None,
    "p_export_w": None,
    "q_import_var": None,
    "q_export_var": None,
    "voltage_v": [231.0, 0.0, 0.0],
    "current_a": [0.0, 0.0, 0.0],
    "p_phase_w": [None, None, None],
    "frequency_hz": None,
    "e_import_wh": 2282950,
    "e_export_wh": 2530,
    "eq_import_varh": None,
    "eq_export_varh": None,
    "flags": 11,
    "fixups_applied": 0,
    "data_interval_ms": 10000,
}


def message(reading: dict[str, Any], euid: str = EUID, topic: str = "reading") -> str:
    """Return a /ws message as aiohttp hands it over: header and payload in one."""
    return f'<device:{euid} topic:"{topic}">{json.dumps(reading)}'


class FakeBridge:
    """The parts of a Tibber bridge's web server the integration talks to."""

    def __init__(self) -> None:
        """Initialize the fake bridge."""
        self.password = PASSWORD
        self.tokens: dict[str, set[str]] = {
            STREAM_TOKEN: {"stream"},
            FULL_TOKEN: {"auth", "stream"},
        }
        self.readings: list[dict[str, Any]] = [copy.deepcopy(READING)]
        self.close_after_send = False
        self.connections = 0
        self.queries: list[dict[str, str]] = []
        self.sockets: list[web.WebSocketResponse] = []
        self.server: TestServer | None = None

    @property
    def host(self) -> str:
        """Return host:port of the server."""
        assert self.server is not None
        return f"{self.server.host}:{self.server.port}"

    def _authorized(self, request: web.Request, scope: str = "auth") -> bool:
        """Check the password (every scope) or a Bearer token holding `scope`."""
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return scope in self.tokens.get(header.removeprefix("Bearer "), set())
        expected = base64.b64encode(f"x:{self.password}".encode()).decode()
        return header == f"Basic {expected}"

    async def ws(self, request: web.Request) -> web.StreamResponse:
        """Serve /ws: send the queued readings, then keep the socket open."""
        if not self._authorized(request, "stream"):
            return web.Response(status=401)
        self.connections += 1
        self.queries.append(dict(request.query))
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        for reading in self.readings:
            await ws.send_str(message(reading))
        if self.close_after_send:
            await ws.close()
            return ws
        async for msg in ws:
            if msg.type == WSMsgType.CLOSE:
                break
        return ws

    async def params(self, request: web.Request) -> web.Response:
        """Serve /params.json, the device id among the params."""
        if not self._authorized(request):
            return web.Response(status=401)
        return web.json_response(
            [
                {"name": "hostname", "type": "string", "value": "Bridge456789ab"},
                {
                    "name": "mqtt_client_id",
                    "type": "string",
                    "value": DEVICE_ID.upper(),
                },
            ]
        )

    async def status(self, request: web.Request) -> web.Response:
        """Serve /status.json."""
        if not self._authorized(request):
            return web.Response(status=401)
        return web.json_response(
            {"firmware": {"esp": "1856-0a3bd598", "efr": "826-0ab1a020"}}
        )

    async def push(self, reading: dict[str, Any]) -> None:
        """Send a reading to every connected client."""
        for ws in list(self.sockets):
            if not ws.closed:
                await ws.send_str(message(reading))
        await asyncio.sleep(0.05)

    async def kick(self) -> None:
        """Close every client, as the bridge does when another takes its place."""
        for ws in list(self.sockets):
            await ws.close()
        self.sockets.clear()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the custom integration in every test."""


@pytest.fixture(autouse=True)
def fast_backoff() -> AsyncGenerator[None]:
    """Reconnect quickly in tests, without aiohttp's heartbeat timers outliving them."""
    with (
        patch("custom_components.tibber_pulse_local.client.BACKOFF_MIN", 0.05),
        patch("custom_components.tibber_pulse_local.client.HEARTBEAT", None),
    ):
        yield


@pytest.fixture
async def bridge(socket_enabled: None) -> AsyncGenerator[FakeBridge]:
    """Run a fake bridge on localhost (the harness blocks sockets otherwise)."""
    fake = FakeBridge()
    app = web.Application()
    app.router.add_get("/ws", fake.ws)
    app.router.add_get("/params.json", fake.params)
    app.router.add_get("/status.json", fake.status)
    fake.server = TestServer(app, host="127.0.0.1")
    await fake.server.start_server()
    yield fake
    for ws in fake.sockets:
        await ws.close()
    await fake.server.close()


@pytest.fixture
def config_entry(bridge: FakeBridge) -> MockConfigEntry:
    """Return a config entry for the fake bridge."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Tibber Bridge {DEVICE_ID}",
        unique_id=DEVICE_ID,
        data={CONF_HOST: bridge.host, CONF_PASSWORD: PASSWORD},
    )


async def wait_for(condition, timeout: float = 3.0) -> None:
    """Wait until condition() holds."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not condition():
        if loop.time() > end:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the entry and wait for the first reading to land."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await wait_for(lambda: bool(entry.runtime_data.meters))
    await hass.async_block_till_done()
