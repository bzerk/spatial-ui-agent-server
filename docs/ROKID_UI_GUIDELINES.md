# Rokid Glasses Surface UI Guidelines

Guidelines ID: `rokid.ui.webxr.v1`

Guidelines version: `2026-09-02`

These rules apply to generated and manually uploaded `spatial.surface.v1` content for the Rokid
WebXR Shell. They are the canonical authoring instructions. A calling agent does not need its own
copy, but it must retrieve this document from the server before uploading authored files.

## Rule Levels

- **Required** rules describe measured display behavior, runtime contracts, accessibility, or
  validation constraints. User requests do not implicitly override them.
- **Default** rules define the house visual language. An explicit request may change the aesthetic,
  but it must continue to satisfy every required rule.

## Display Geometry (Required)

- The physical Android bitmap is 480 x 640 pixels.
- The WebView layout viewport is exactly 320 x 427 CSS pixels at `devicePixelRatio` 1.5.
- Use `width: 100vw` and `height: 100vh`. Never author a fixed 480 x 640 CSS page.
- Keep essential content inside the centered 266 x 381 CSS-pixel safe area. Its CSS insets are
  27px left, 23px top, 27px right, and 23px bottom.
- Treat the safe area as a clipping boundary, not a target for filling every pixel.
- Test long text, generated values, error states, and controls at the actual 320 x 427 viewport.
  Do not assume a phone, desktop, or landscape browser viewport.

Use this viewport declaration:

```html
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
```

## Optical Black and Compositing (Required)

On the tested glasses, optical black is produced by transparent WebView and canvas pixels. Opaque
CSS black was measured as a visible gray compositor floor. Therefore:

- Keep `html`, `body`, and every full-viewport layer transparent.
- Do not paint `#000`, `#000000`, `black`, near-black substitutes, or full-screen tinted layers.
- Clear 2D canvases with `clearRect()` instead of filling them black.
- Clear WebGL with `gl.clearColor(0, 0, 0, 0)`.
- Keep renderer, scene, canvas, CSS, and native-root alpha behavior aligned. A transparent body does
  not help if another full-screen layer is opaque.
- Do not use gradients. They increase emissive area and are rejected by the current validator.

Transparent pixels look black on the optical display. Transparency does not mean that the scene
should be composited over a decorative webpage background.

## Comfort and Horizon (Required)

- Do not require the wearer to look more than a couple of degrees above the horizon.
- Place primary world-fixed content at the horizon or below it. A useful default elevation is 0 to
  -10 degrees.
- Keep required status and interaction targets near the center or in the lower portion of the safe
  area. Top-edge content should be secondary and brief.
- Avoid dense content at the extreme optical edges. Preserve breathing room for head motion and
  imperfect fit.
- If world-fixed content moves off-screen, preserve its real relative direction. It must re-enter
  immediately when the wearer turns back; do not drag or re-anchor the scene at the clipped edge.

## Visual Language

### Required

- Treat emissive area as a limited budget. Avoid large bright fills, thick glowing borders, and
  large contiguous luminous regions.
- Prefer concise labels and progressive disclosure over paragraphs of persistent instruction.
- Do not ship an unchanged phone-style Material layout, phone frame, tab bar, or bottom navigation.
- Do not depend on color alone for selection or status.
- Keep focus precise and visible without obscuring content.
- Do not show implementation provenance, manifests, hashes, repository state, generated-by labels,
  or validation commentary in the primary user interface unless a developer view was requested.

### Default

- Use compact monospace typography, normally 8px to 11px in the CSS viewport.
- Use fine green primary text and strokes, with gray or subdued green secondary information.
- Prefer hairline outlines, separators, brackets, reticles, and unfilled geometry.
- Show focus with a marker, bracket, underline, or fine accent rather than a filled card.
- Avoid oversized app titles, decorative gradients, pill controls, and large cards.

The default aesthetic is not a prohibition on a deliberately requested visual style. Games,
visualizations, document readers, and other generated experiences may look substantially different
while retaining transparent optical black, bounded emissive area, legibility, and input support.

## Input and Interaction (Required)

- Never require a touchscreen. The glasses have a tap surface, not a conventional touch display.
- The container owns single-tap voice start/stop, long-press cancellation, and double-tap exit.
  Do not make a surface action depend exclusively on those gestures.
- The middle third of the top edge plus a secondary mouse click is reserved for the native prompt
  menu. The top-right native status HUD may open Wi-Fi settings. Keep essential surface controls out
  of those overlay regions.
- Support normal pointer and click events for optional HID mice, trackballs, air mice, and rings.
- Support wheel and directional-key scrolling when the experience scrolls.
- Do not require hover. Keep keyboard focus usable when keyboard-like HID input is present.
- Provide a visible focus or center reticle for head-directed selection when that interaction is
  requested. A control must remain operable without hand tracking.
- Do not claim hand tracking, 6DOF, or controller input unless the runtime reports that capability.

## 3DOF and WebXR (Required)

Use the calibrated runtime contract instead of deriving another sensor-axis mapping:

```js
const unsubscribe = window.rokid.spatial.subscribe((pose) => {
  const steeringYaw = pose.head.yawDeg;
  const worldTransform = pose.stage.quaternion;
  const relative = window.rokid.spatial.worldToView({
    azimuthDeg: 20,
    elevationDeg: -8,
  });
});
```

- Use `pose.head` for head-directed controls such as steering.
- Use `pose.stage`, `worldToView()`, or `parallax()` for world-fixed presentation.
- The container has already calibrated the Rokid landscape axes. Do not swap or invert them, build a
  new Euler-to-quaternion conversion, or interpret browser `deviceorientation.alpha` as WebXR Z
  rotation.
- `pose.stage.quaternion` is already the world-to-view transform. Do not invert it again.
- Inline WebXR uses the same `rokid.spatial.pose.v1` orientation contract.
- Treat the runtime as 3DOF. Viewer position is fixed at zero; do not imply positional tracking.
- Check `navigator.xr.isSessionSupported()` before requesting a session. Inline may be available
  while immersive modes are unavailable.

## Camera and Native Capabilities (Required)

- Browser video uses `navigator.mediaDevices.getUserMedia({video: true})` when available.
- Stop browser video tracks and call `window.rokid.camera.releaseVideo()` before requesting a native
  still.
- Query `window.rokid.runtime.capabilities()` rather than assuming camera, voice, or WebXR features.
- Keep a useful non-camera state when permission, lease, or hardware availability prevents capture.
- Native results arrive through the `rokidnative` event. Do not expose raw bridge diagnostics in the
  primary UI.

## External Resources and Live Data (Required)

- Bundle executable code and presentation assets locally. Do not embed remote scripts, modules,
  stylesheets, frames, WebAssembly, fonts, images, models, audio, or CDN dependencies.
- Do not fabricate current document contents, printer telemetry, prices, or other live values.
- Data supplied with the generation request may be rendered with its timestamp.
- When requested live data is unavailable, show an explicit unavailable or stale state while
  retaining a useful interface shell.
- Trusted server-owned connectors and declared data channels are the intended path for live data.
  See [Network Capabilities and External Resources](NETWORK_CAPABILITIES.md).

## Surface Package (Required)

- Return complete functional HTML, CSS, and JavaScript using relative paths.
- Include `index.html` with the required viewport metadata.
- Use UTF-8 text files and traversal-free relative paths. Do not use symlinks.
- Emit no more than 127 content files and 8 MiB unpacked. The server adds `surface.json` as the
  possible 128th entry.
- Do not emit `surface.json`; the server creates the immutable manifest.
- Do not use `eval()` or `new Function()`.
- Keep a short speech summary separate from visual content. It must describe the result without
  reading code, markup, controls, filenames, URLs, or display-only detail aloud.

## External-Agent Workflow

An agent using MCP should:

1. Call `surface_guidelines_get` and retain its `sha256`.
2. Call `device_surface_get` before modifying a live device so the edit starts from its exact source.
3. Author against this document and the returned source.
4. Call `surface_put` with the authored files and the exact guideline SHA-256.
5. Resolve any validator errors, then call `surface_push` with the stored revision.

The built-in `surface_generate` and `surface_generate_and_push` paths inject this complete document
automatically.
