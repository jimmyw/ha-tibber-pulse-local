# Tibber Pulse (local)

A Home Assistant integration that reads your electricity meter **locally**, from a Tibber
bridge on your network, without the cloud. The bridge decodes the data its Pulse
devices read from the meter, and streams each decoded reading over its local websocket
(`/ws`). This integration listens on that stream and turns every reading into sensors.

Readings arrive as the meter sends them, typically every 2–10 seconds; nothing is polled.

## Requirements

- A Tibber bridge on your local network, or a Pulse P1 running the bridge firmware, with
  firmware that has the `/ws` stream filter (`/ws?kind=reading`). That firmware is on the
  bridge `main` branch.
- The bridge's **meter_parser** module loaded. It decodes the meter's data on the
  bridge; without it the stream carries no readings, and no sensors appear.
- A credential for the bridge: an **API token** with the `stream` scope (recommended, see
  [API tokens](#api-tokens)), or its web password, the code on its QR label, like
  `ABCD-1234`.

## Installation (HACS)

1. In HACS, open the menu → **Custom repositories**, add this repository's URL with
   category **Integration**.
2. Install **Tibber Pulse (local)** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → Tibber Pulse (local)**, and enter the
   bridge's IP address or host name, and either an API token or the web password (one of
   the two, leave the other empty). Bridges on the same network are also discovered over
   mDNS; then only the token or password is asked for.

Discovery finds the bridge by the web server it advertises, `Tibber Bridge Web
Server._http._tcp` (`Pulse P1 Web Server` on a Pulse P1), which it does while that server
runs: with the web interface on, or with an API token on the bridge. Home Assistant follows
a discovered bridge to a new IP address. Check what your bridge advertises with `avahi-browse -r _http._tcp` (Linux) or
`dns-sd -B _http._tcp` (macOS).

Manual install: copy `custom_components/tibber_pulse_local` into your Home Assistant
`config/custom_components/` and restart.

## API tokens

An API token lets Home Assistant read the stream without the bridge's web password, and
only what the token's scopes allow. It is the better choice:

- A `stream` token opens the live data on `/ws` and nothing else: not the settings, the
  console or firmware uploads that the password opens.
- It keeps working when the bridge's web interface is turned off in its
  **Configuration**; then the password opens nothing, but tokens still do.
- It can be revoked on its own, without changing the password everything else uses.

Tokens need bridge firmware with API token support, on the bridge `main` branch.

### Create a token in the web interface

1. Open `http://<bridge>/` (its IP address, or `bridgeXXXXXXXX.local`) and log in with the
   web password, the code on the bridge's QR label.
2. Open **API tokens** in the menu, and **Create token**.
3. Name it, e.g. `home_assistant` (1–15 of `a-z 0-9 _ -`), and tick the **stream** scope
   only.
4. **Copy the token now.** It is shown this once: the bridge keeps only a hash of it. If
   you lose it, remove it and create a new one.

Paste it into the **API token** field when you add the integration, and leave the password
empty. Once it works, you can turn the web interface off in **Configuration** if you like.

### Or on the bridge console

Over the bridge's serial console (or the **Console** page of its web interface, shown in
developer mode):

```text
ws_token add home_assistant stream        # prints the token, the only time it is shown
ws_token add home_assistant stream 365d   # one that expires: never (default), 30d, 12h, a unix time
ws_token list                             # names, scopes and expiry, never the tokens
ws_token rm home_assistant                # revoke it
ws_token scopes                           # the scopes this bridge knows
```

A bridge holds up to 8 tokens. One that expires is refused until the bridge's clock is
set (over NTP), and removed once it has expired.

### What a stream token cannot do

A `stream` token does not open `/params.json` or `/status.json`, so Home Assistant does not
learn the bridge's device id or firmware version through it. The bridge's device then has
no firmware version, and a bridge added by address is identified by that address; one
found over mDNS keeps the id from its host name. A token with the `auth` scope (or `full`)
opens those pages too, like the password.

Removing a token, or letting it expire, closes Home Assistant's stream at once, and Home
Assistant asks for a new token or the password.

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

The integration opens `ws://<bridge>/ws?kind=reading`, sending an API token as
`Authorization: Bearer <token>`, or the web password with HTTP Basic authentication (any
user name), and reconnects with a backoff from 1 to 60 seconds when the connection drops.
If the bridge stops accepting the token or password, Home Assistant asks for a new one.

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
`scripts/smoke.py [--token] <host> <password or token> [seconds]` streams from a real bridge
with the integration's client and prints each reading.

## License

MIT
