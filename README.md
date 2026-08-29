# Spatial UI Agent Server

Laptop-local voice, camera-context, generation, and MCP runtime for
[`rokid-webxr-shell`](https://github.com/bzerk/rokid-webxr-shell).

Laptop-local Starlette server for the approved Rokid spatial UI demo. It accepts authenticated
voice turns, keeps a persistent local Whisper worker warm when configured, generates constrained
HTML/CSS/JS surfaces with Codex CLI, validates and stores immutable `spatial.surface.v1` bundles,
and delivers commands over replayable device WebSockets. SQLite is the durable authority.

## Setup

Requires Python 3.11+, `uv`, and Codex CLI authentication.

```sh
uv sync --extra dev
cp .env.example .env
./scripts/generate-token device
./scripts/generate-token mcp
```

Set machine-specific values only in untracked `.env`. For the current laptop worker, set
`SPATIAL_TRANSCRIBER_BIN` to the actual `arux-whisper-worker` path and
`SPATIAL_WHISPER_MODEL` to an available whisper.cpp model. Transcription fails closed by default;
the explicit `fixture` fallback is only for plumbing tests and reports `degraded` in `/health`.
Codex generation defaults to a 600-second bound and emits durable status heartbeats every 15
seconds while waiting. A timeout becomes a bounded diagnostic error and terminates its process
group.

For a laptop-local Rokid demo, configure this server and a sibling client without putting
credentials on the command line:

```sh
uv run scripts/configure_demo.py --address YOUR_LAPTOP_LAN_IP
./scripts/run
```

The configurator creates ignored mode-0600 token files, writes this repository's ignored `.env`,
and updates the client's ignored `local.properties`. It defaults to
`~/AndroidStudioProjects/RokidWebXRShell`, port `8766`, an `arux-whisper-worker` executable found on
`PATH`, and the official cached `ggml-base.en` model. Override those paths with command-line flags
when needed.

Set `SPATIAL_MDNS_ADDRESS` and `SPATIAL_PUBLIC_BASE_URL` to the laptop interface reachable by the
glasses. Addresses are intentionally not tracked because DHCP/interface state can change.

```sh
./scripts/run
curl http://127.0.0.1:8766/health
```

The admin page is available only from the server's loopback interface at
`http://127.0.0.1:8766/admin`. Device routes require the device bearer token. MCP uses a distinct
token and source allowlist.

## Device API

- `POST /v1/turns`: multipart fields `audio` (PCM16 mono 16 kHz WAV), optional `photo` (JPEG),
  optional JSON-object `context`, UUID `event_id`, and `device_id`. Reusing an `event_id` returns
  the existing turn with HTTP 202.
- `GET /v1/turns/{id}`: durable turn state.
- `GET /v1/surfaces/{revision}.zip`: immutable validated bundle with long-lived cache headers.
- `WS /v1/devices/{id}/events?cursor={seq}`: replay events after a durable sequence cursor.
  Emitted events follow `spatial.event.v1` and use `turn.status`, `surface.available`, or
  `device.command`. Clients acknowledge with `spatial.ack.v1`; valid states are `downloaded`,
  `loaded`, `rendered`, and `failed`.
- `GET /health`: dependency and active-revision status without secret values.

Example turn:

```sh
curl -H "Authorization: Bearer $DEVICE_TOKEN" \
  -F event_id=demo-001 -F device_id=rokid-demo \
  -F audio=@turn.wav -F photo=@view.jpg -F 'context={"capabilities":{}}' \
  http://127.0.0.1:8766/v1/turns
```

## Surface Contract

Every ZIP includes server-generated `surface.json` with schema `spatial.surface.v1`, immutable
revision, `index.html` entrypoint, SHA256 file map, `transparent-ar` background mode, capabilities,
and both the 480x640 Android bitmap and 320x427 CSS viewport at DPR 1.5. The validator limits
bundles to 128 files and 8 MiB and
rejects unsafe paths, remote resources, gradients, opaque or near-black backgrounds, full-screen
tinted layers, phone-layout markers, out-of-bounds dimensions, and dynamic JavaScript evaluation.
On the tested Rokid WebView, transparent root layers and clear canvases produce optical black;
opaque CSS `#000000` produced a measurable compositor floor and is intentionally rejected.

Built-ins are a default 3DOF constellation and a yaw-controlled brick-breaker fixture.

## MCP

The official MCP Python SDK serves Streamable HTTP at `/mcp` and stdio through:

```sh
./scripts/run-mcp-stdio
```

Tools: `devices_list`, `surface_get_active`, `surface_generate`, `surface_put`, `surface_push`,
`surface_reset`, `device_capture_camera`, `device_capture_display`, and `device_speak`. Successful
turn generation preserves a short speech-safe Codex summary and queues it after
`surface.available` as an idempotent `device.command` with `command: "speak"`; code and
display-only content are never used as speech text.

For local operator checks, `./scripts/call-mcp TOOL '{"argument":"value"}'` uses the ignored MCP
credential file without exposing its value in the command line or output.

## Verification

```sh
uv run ruff check .
uv run pytest
./scripts/smoke-transcriber
./scripts/smoke-server  # while ./scripts/run is active
./scripts/smoke-turn    # live Whisper + Codex turn against the active server
```

Physical acceptance still requires a real client connection and `rendered` acknowledgement; the
server test suite alone is not a substitute.

Compatibility is input-only: multipart `image` is accepted as a legacy alias for `photo`, and the
earlier `{type:"ack",status:"..."}` acknowledgement is accepted. The server always emits the
frozen schemas and names above.
