# ruff: noqa: INP001, T201  (a command-line tool, not part of the integration)
"""Stream readings from a real bridge with the integration's client, for a while.

Usage: python scripts/smoke.py [--token] <host> <password or API token> [seconds]
"""

import asyncio
import pathlib
import sys

import aiohttp

sys.path.insert(
    0,
    str(pathlib.Path(__file__).parents[1] / "custom_components" / "tibber_pulse_local"),
)
from client import Reading, TibberPulseClient


async def main(host: str, credential: str, token: bool, seconds: float) -> None:
    """Connect, print each reading and connection change, then stop."""

    def on_reading(reading: Reading) -> None:
        data = reading.data
        print(
            f"reading {reading.euid}: {data.get('decoded_as')} U={data.get('voltage_v')} "
            f"I={data.get('current_a')} P+={data.get('p_import_w')} "
            f"E+={data.get('e_import_wh')} Wh E-={data.get('e_export_wh')} Wh"
        )

    async with aiohttp.ClientSession() as session:
        client = TibberPulseClient(
            session,
            host,
            None if token else credential,
            on_reading,
            on_connection=lambda up: print("stream", "up" if up else "down"),
            on_auth_failed=lambda: print("credential refused"),
            api_token=credential if token else None,
        )
        await client.async_validate()
        print("device id", await client.async_get_device_id())
        print("firmware", ((await client.async_get_status()) or {}).get("firmware"))
        task = asyncio.create_task(client.run())
        await asyncio.sleep(seconds)
        task.cancel()


if __name__ == "__main__":
    args = sys.argv[1:]
    token = "--token" in args
    if token:
        args.remove("--token")
    asyncio.run(main(args[0], args[1], token, float(args[2]) if len(args) > 2 else 30))
