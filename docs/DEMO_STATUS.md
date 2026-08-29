# Demo Status

## Implemented

- Laptop-local Starlette API with SQLite persistence and mDNS advertisement.
- Deterministic SQLite transaction closure; 250 live health reads left zero database/WAL file
  descriptors open in the server process.
- Separate bearer credentials for device API and MCP, with MCP source allowlist.
- Idempotent multipart turn intake and durable turn status.
- Replayable per-device WebSocket events and durable acknowledgements.
- Immutable `spatial.surface.v1` packaging and procedural validation.
- Default 3DOF constellation and yaw brick-breaker fixtures.
- Persistent JSONL `arux-whisper-worker` integration, optional prewarm, WAV conversion, and an
  explicit degraded fixture fallback.
- Codex CLI generator using configured `gpt-5.6-sol`, low reasoning, ephemeral workspace-write,
  optional image input, JSON schema output, active-source continuity, and one repair pass.
- Official MCP SDK adapter with Streamable HTTP and stdio transports.
- Post-push TTS command sourced from a bounded, speech-safe Codex summary and idempotent per turn.

## Live Acceptance

Verified on an attached RG_glasses on 2026-08-30:

- `/health` reported the persistent Whisper worker ready with fallback disabled.
- A fresh device turn uploaded a 16 kHz WAV and correlated JPEG under one event ID.
- Whisper returned a real raw transcript, although the unattended speaker-to-microphone test was
  inaccurate and needs a worn-device retest.
- Codex generated and validated new surfaces from both the device turn and an authorized MCP call.
- The client acknowledged `downloaded`, `loaded`, and `rendered` for generated revisions.
- A server restart plus Wi-Fi interruption replayed a queued event after client reconnect.
- The live WebView measured 320x427 CSS pixels at DPR 1.5 on a 480x640 Android bitmap.
- Empty display samples measured exact RGB `0,0,0` with the transparent optical-black path.
- Injected runtime APIs created an inline WebXR viewer session and rejected immersive mode.
- JavaScript acquired and released a real environment-facing camera track at 480x640 and 60 fps.
- Device-side TTS returned a `spoken` execution acknowledgement.

## Remaining Human Gates

- Confirm physical single tap, long press, and double-tap behavior; current capture was triggered
  with ADB key injection through the same key path.
- Confirm audible TTS and comfortable 3DOF yaw/pitch/roll while wearing the glasses.
- Repeat speech capture while worn so microphone placement, rather than unattended room acoustics,
  is represented.
- Isolate mDNS-only discovery; the deterministic LAN fallback is proven.
