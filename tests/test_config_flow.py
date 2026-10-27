"""Tests for the Tibber Pulse (local) config flow."""

from ipaddress import ip_address

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tibber_pulse_local.const import DOMAIN
from homeassistant import config_entries
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .conftest import (  # noqa: TID251
    DEVICE_ID,
    FULL_TOKEN,
    PASSWORD,
    STREAM_TOKEN,
    FakeBridge,
)


async def test_user_flow(hass: HomeAssistant, bridge: FakeBridge) -> None:
    """A reachable bridge with the right password is added under its device id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: bridge.host, CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == DEVICE_ID
    assert result["data"] == {CONF_HOST: bridge.host, CONF_PASSWORD: PASSWORD}
    assert bridge.queries[0] == {"kind": "reading"}


async def test_user_flow_invalid_auth(hass: HomeAssistant, bridge: FakeBridge) -> None:
    """A refused password is reported, and a corrected one goes through."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: bridge.host, CONF_PASSWORD: "WRONG"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: bridge.host, CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_stream_token(hass: HomeAssistant, bridge: FakeBridge) -> None:
    """A stream token opens /ws only: added under its host, not its device id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: bridge.host, CONF_API_TOKEN: STREAM_TOKEN}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == bridge.host
    assert result["data"] == {CONF_HOST: bridge.host, CONF_API_TOKEN: STREAM_TOKEN}


async def test_user_flow_full_token(hass: HomeAssistant, bridge: FakeBridge) -> None:
    """A full token also reads the device id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: bridge.host, CONF_API_TOKEN: FULL_TOKEN}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == DEVICE_ID


async def test_user_flow_invalid_token(hass: HomeAssistant, bridge: FakeBridge) -> None:
    """A token the bridge does not know is refused like a wrong password."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: bridge.host, CONF_API_TOKEN: "unknown"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_one_credential(
    hass: HomeAssistant, bridge: FakeBridge
) -> None:
    """Exactly one of password and token is asked for."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    for credentials in (
        {},
        {CONF_PASSWORD: " "},
        {CONF_PASSWORD: PASSWORD, CONF_API_TOKEN: STREAM_TOKEN},
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: bridge.host, **credentials}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "credentials"}
    assert bridge.connections == 0


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, bridge: FakeBridge
) -> None:
    """Nothing listening is reported as cannot_connect."""
    await bridge.server.close()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: bridge.host, CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, bridge: FakeBridge, config_entry: MockConfigEntry
) -> None:
    """The same bridge at a new address updates the existing entry."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE_ID,
        data={CONF_HOST: "1.2.3.4", CONF_PASSWORD: PASSWORD},
    )
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: bridge.host, CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data[CONF_HOST] == bridge.host


def _zeroconf(hostname: str = "Bridge456789ab.local.") -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address("127.0.0.1"),
        ip_addresses=[ip_address("127.0.0.1")],
        hostname=hostname,
        name="Tibber Bridge Web Server._http._tcp.local.",
        port=80,
        type="_http._tcp.local.",
        properties={},
    )


async def test_zeroconf_flow(hass: HomeAssistant, bridge: FakeBridge) -> None:
    """A discovered bridge asks for its password, then is added under its device id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_zeroconf()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"
    # The fake bridge listens on another port than the advertised one
    flow = hass.config_entries.flow._progress[result["flow_id"]]  # noqa: SLF001
    flow._host = bridge.host  # noqa: SLF001
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == DEVICE_ID


async def test_zeroconf_flow_stream_token(
    hass: HomeAssistant, bridge: FakeBridge
) -> None:
    """A discovered bridge added with a stream token keeps its mDNS id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_zeroconf()
    )
    flow = hass.config_entries.flow._progress[result["flow_id"]]  # noqa: SLF001
    flow._host = bridge.host  # noqa: SLF001
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: STREAM_TOKEN}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "456789ab"
    assert result["data"] == {CONF_HOST: bridge.host, CONF_API_TOKEN: STREAM_TOKEN}


async def test_zeroconf_known_bridge_updates_host(hass: HomeAssistant) -> None:
    """A configured bridge found at a new address gets that address."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE_ID,
        data={CONF_HOST: "1.2.3.4", CONF_PASSWORD: PASSWORD},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_zeroconf()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "127.0.0.1"


async def test_zeroconf_not_a_bridge(hass: HomeAssistant) -> None:
    """Another device's web server is ignored."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=_zeroconf("printer.local."),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_tibber_bridge"


async def test_reauth(
    hass: HomeAssistant, bridge: FakeBridge, config_entry: MockConfigEntry
) -> None:
    """A new password replaces the refused one."""
    bridge.password = "NEW1-PASS"
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "NEW1-PASS"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "NEW1-PASS"


async def test_reauth_with_token(
    hass: HomeAssistant, bridge: FakeBridge, config_entry: MockConfigEntry
) -> None:
    """A token can take the place of a refused password."""
    bridge.password = "NEW1-PASS"
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: STREAM_TOKEN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data == {CONF_HOST: bridge.host, CONF_API_TOKEN: STREAM_TOKEN}
