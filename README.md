# Tibber Pulse (local)

A Home Assistant integration that reads your electricity meter **locally**, from a Tibber
bridge on your network, without the cloud. The bridge decodes the data its Pulse
devices read from the meter, and streams each decoded reading over its local websocket
(`/ws`). This integration listens on that stream and turns every reading into sensors.

Readings arrive as the meter sends them, typically every 2–10 seconds; nothing is polled.

## Requirements

- A Tibber bridge on your local network, with bridge firmware that has the `/ws` stream
  filter (`/ws?kind=reading`). That firmware is on the bridge `main` branch.
- The bridge's **meter_parser** module loaded. It decodes the meter's data on the
  bridge; without it the stream carries no readings, and no sensors appear.
- The bridge's web password: the code on its QR label, like `ABCD-1234`.

## Installation (HACS)

1. In HACS, open the menu → **Custom repositories**, add this repository's URL with
   category **Integration**.
2. Install **Tibber Pulse (local)** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → Tibber Pulse (local)**, and enter the
   bridge's IP address or host name and its web password. Bridges on the same network
   are also discovered over mDNS; then only the password is asked for.

Manual install: copy `custom_components/tibber_pulse_local` into your Home Assistant
`config/custom_components/` and restart.

## Devices and entities

The bridge becomes a device, and each meter behind it a device of its own, linked to the
bridge. A meter's device appears with its first reading. A meter only gets the sensors
for values it actually reports; if a value starts to appear later, its sensor is added
then.

| Sensor | Unit | Notes |
| --- | --- | --- |
| Power | W | Net: import minus export |
| Power import / export | W | |
| Power L1–L3 | W | Per phase, when the meter reports it |
| Voltage L1–L3 | V | |
| Current L1–L3 | A | |
| Frequency | Hz | |
| Energy import / export | kWh | `total_increasing`: use these in the Energy dashboard |
| Reactive power import / export | var | Disabled by default |
| Reactive energy import / export | kvarh | Disabled by default |

Many meters read through a Pulse IR (IEC 62056-21 optical port) report voltage, current
and energy but **no power**. Such a meter has no power sensors: this integration shows
what the meter says and does not estimate.

A meter's sensors become unavailable when the stream is down, or when no reading arrived
for three reading intervals (at least 60 seconds).

## How it connects

The integration opens `ws://<bridge>/ws?kind=reading` with HTTP Basic authentication (any
user name, the web password) and reconnects with a backoff from 1 to 60 seconds when the
connection drops. If the bridge stops accepting the password, Home Assistant asks for the
new one.

The bridge serves a limited number of `/ws` clients at once. Firmware that serves a single
client closes the previous one when a new one connects, so Home Assistant and the bridge's
own live-data web page would take the stream from each other. Use bridge firmware that
serves several clients (three) when you also use that page.

## Development

```bash
uv venv -p python3.14 .venv
uv pip install -p .venv/bin/python -r requirements_test.txt
.venv/bin/python -m pytest
```

The tests run a fake bridge on localhost; they need no hardware.
`scripts/smoke.py <host> <password> [seconds]` streams from a real bridge with the
integration's client and prints each reading.

## License

MIT
