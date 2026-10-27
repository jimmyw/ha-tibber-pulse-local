"""Tests for parsing the bridge's /ws messages."""

from custom_components.tibber_pulse_local.client import (
    auth_header,
    bearer_header,
    parse_message,
)

from .conftest import EUID, READING, message  # noqa: TID251


def test_parse_reading() -> None:
    """A reading message gives its euid and data, nulls kept."""
    reading = parse_message(message(READING))
    assert reading is not None
    assert reading.euid == EUID
    assert reading.data["e_import_wh"] == 2282950
    assert reading.data["p_import_w"] is None
    assert reading.data["voltage_v"] == [231.0, 0.0, 0.0]


def test_parse_bytes_and_upper_case_euid() -> None:
    """Binary frames and upper-case euids are accepted."""
    reading = parse_message(message(READING, euid=EUID.upper()).encode())
    assert reading is not None
    assert reading.euid == EUID


def test_parse_ignores_other_topics() -> None:
    """Raw frames and CT readings are not readings."""
    assert parse_message(message(READING, topic="iec")) is None
    assert parse_message(message(READING, topic="clamp")) is None


def test_parse_malformed() -> None:
    """Anything malformed is dropped, not raised."""
    assert parse_message("") is None
    assert parse_message("{}") is None
    assert parse_message('<device:123 topic:"reading">{}') is None
    assert parse_message(f'<device:{EUID} topic:"reading">not json') is None
    assert parse_message(f'<device:{EUID} topic:"reading">[1, 2]') is None
    assert parse_message(f'<device:{EUID} topic:"reading"') is None
    assert parse_message(b"\xff\xfe") is None


def test_auth_header() -> None:
    """The bridge takes any user name, the password is what counts."""
    assert auth_header("TEST-PASS") == {"Authorization": "Basic eDpURVNULVBBU1M="}


def test_bearer_header() -> None:
    """An API token goes as a Bearer token."""
    assert bearer_header("abc") == {"Authorization": "Bearer abc"}
