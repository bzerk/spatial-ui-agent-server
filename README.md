# Spatial UI Agent Server

Laptop-local voice, camera-context, generation, and MCP runtime for
[`rokid-webxr-shell`](https://github.com/bzerk/rokid-webxr-shell).

Laptop-local Starlette server for the approved Rokid spatial UI demo. It accepts authenticated
voice turns, keeps a persistent local Whisper worker warm when configured, generates constrained
HTML/CSS/JS surfaces with Codex CLI, validates and stores immutable `spatial.surface.v1` bundles,
and delivers commands over replayable device WebSockets. SQLite is the durable authority.

The complete runtime is laptop-owned. It has no Axiom, Tailscale, hosted router, or public-ingress
dependency. The glasses connect directly to this server over the current private LAN using mDNS or
an address-free UDP discovery probe. The client derives the HTTP endpoint from the responder's
packet source, so DHCP and switching between home Wi-Fi and a MiFi do not require rebuilding the
APK. MCP clients and Codex also run locally on, or connect directly to, this laptop.

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
uv run scripts/configure_demo.py
./scripts/service install
./scripts/service open
```

The configurator creates ignored mode-0600 token files, writes this repository's ignored `.env`,
and updates the client's ignored `local.properties`. It defaults to
`~/AndroidStudioProjects/RokidWebXRShell`, port `8766`, an `arux-whisper-worker` executable found on
`PATH`, and the official cached `ggml-base.en` model. Override those paths with command-line flags
when needed.

The normal path has no configured laptop address. The server listens for
`SPATIAL_UI_DISCOVER_V1` on UDP `8767` and replies with only its protocol and HTTP port; the glasses
use the packet source as the host. UDP discovery is the portable demo default because stale mDNS
interface state can survive a Wi-Fi change on macOS. mDNS remains available as an opt-in
standards-based path. An explicit `SPATIAL_MDNS_ADDRESS` is a diagnostic override, not a demo
requirement.

The LaunchAgent starts at login, restarts after failure, and does not depend on an agent terminal
remaining open. Lifecycle commands are:

```sh
./scripts/service status
./scripts/service restart
./scripts/service logs
./scripts/service stop
./scripts/service start
```

`./scripts/run` remains the foreground development command. The application log rotates at
`~/Library/Logs/SpatialUIAgent/server.log`; launchd stdout and stderr are in the same directory.

The operator console is available only from the server's loopback interface at
`http://127.0.0.1:8766/admin`. It shows live health, devices, turns, delivery acknowledgements,
generation jobs, and the rotating log. It can generate and push a surface, re-push the active
surface, reset either fixture, request camera/display capture, and queue device speech. Mutations
require a process-local CSRF token embedded in the loopback page. Device routes require the device
bearer token; MCP uses a distinct token and source allowlist.

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
  A client also sends `spatial.runtime.snapshot.v1` after each page load. Bundled content includes
  its exact UTF-8 source files; downloaded content reports its immutable revision. The server
  replies with `spatial.runtime.snapshot.accepted.v1` only after that source is available to MCP.
- `GET /health`: dependency and active-revision status without secret values.

Example turn:

```sh
curl -H "Authorization: Bearer $DEVICE_TOKEN" \
  -F event_id=8e41232b-9df6-42ef-8bf4-ad03fe82fcaf -F device_id=rokid-demo \
  -F audio=@turn.wav -F photo=@view.jpg -F 'context={"capabilities":{}}' \
  http://127.0.0.1:8766/v1/turns
```

## Rokid UI Guidelines

[`docs/ROKID_UI_GUIDELINES.md`](docs/ROKID_UI_GUIDELINES.md) is the canonical, versioned design and
runtime guide for every generated or manually authored surface. It covers the measured viewport and
safe area, transparent optical-black compositing, comfortable horizon placement, visual density,
input assumptions, calibrated 3DOF/WebXR use, camera ownership, connected-data honesty, and package
limits.

The built-in generator injects that exact document automatically. External MCP agents must call
`surface_guidelines_get`, author against the returned text, and pass its SHA-256 to `surface_put`.
This makes the server the source of design rules instead of relying on the caller's private prompt.
Every generated manifest records the guideline ID, version, and digest under `designGuidelines`.

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
Generated surfaces receive `window.rokid.spatial`, whose calibrated `head`, world-to-view `stage`,
`worldToView()`, and `parallax()` values preserve the known-good Obsidian axis convention. Inline
WebXR uses the same pose contract instead of interpreting browser `alpha` as a Z-axis yaw.

## External Content and Live Data

The self-contained bundle rule is a deliberate current capability boundary, not a claim that useful
spatial applications should never access the network. Today the validator rejects remote embedded
scripts, styles, frames, imports, and asset URLs. Direct runtime HTTPS may technically work under
normal WebView and CORS rules, but it has no manifest policy, credential broker, freshness model,
or client-side allowlist and is not a supported contract.

Consequently, a generated surface may display data supplied with its request, but it must not
invent or imply live document contents, printer telemetry, market prices, or other current data.
Those use cases require a trusted server-side connector or a future declared network capability.
See [Network Capabilities and External Resources](docs/NETWORK_CAPABILITIES.md) for the exact
current behavior, security rationale, examples, and intended asset-import/data-channel design.

## MCP

The official MCP Python SDK serves Streamable HTTP at `/mcp` and stdio through:

```sh
./scripts/run-mcp-stdio
```

Tools: `surface_guidelines_get`, `devices_list`, `device_surface_get`, `surface_get_active`,
`surface_source_get`, `surface_generate`, `surface_generate_and_push`, `surface_put`,
`surface_push`, `surface_reset`, `device_capture_camera`, `device_capture_display`, and
`device_speak`. The intended external-agent live-edit flow is `surface_guidelines_get`, then
`device_surface_get`, then `surface_put` with `guidelines_sha256`, followed by `surface_push`.
Alternatively, call `surface_generate_and_push` to use the server's guide-backed generator directly
against the exact source reported by that device.
Successful
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
