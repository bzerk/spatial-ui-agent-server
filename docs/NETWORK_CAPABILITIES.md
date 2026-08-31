# Network Capabilities and External Resources

The treatment of external resources is a product capability boundary, not an incidental validator
detail. It determines whether a generated surface can display a remote document, subscribe to a
3D printer, show market data, import a library, or embed an arbitrary website.

## Current Contract

`spatial.surface.v1` packages are currently designed as self-contained, immutable bundles. The
validator rejects literal remote references in HTML, CSS, and JavaScript imports, including remote
`src`, `href`, `url(...)`, and `import` values. Generated surfaces are therefore expected to carry
their executable code and presentation assets inside the hash-addressed bundle.

This restriction applies to embedded resources. It does not define a complete runtime network
sandbox. The Android client has network permission, and its WebView can make outbound HTTPS
requests that satisfy normal browser rules. A dynamically constructed `fetch()` URL may therefore
work, but direct fetching is not currently a supported surface contract:

- there is no manifest-declared origin policy;
- there is no client-side request allowlist or complete request audit;
- cross-origin requests still depend on the remote server's CORS policy;
- no credential broker safely keeps service credentials off the glasses;
- there are no standard timeout, caching, freshness, rate-limit, or offline semantics;
- the validator's URL checks are authoring guidance, not a complete security boundary.

Generated surfaces must not claim that data is current unless the request supplies current data or
an explicit connector provides it. A UI that silently substitutes invented data is invalid.

## Why Remote Code Is Different

The surface runs in the same WebView context as `RokidNative`, which exposes camera capture, voice
turns, Wi-Fi settings, orientation reset, surface activation, and device information. Arbitrary
remote scripts or frames would introduce mutable third-party code into that privileged context.
They also make an immutable revision non-reproducible: the same surface hash could behave
differently after a CDN asset changes.

Remote executable code, modules, HTML, stylesheets, WebAssembly, and frames should therefore stay
forbidden in the privileged surface until the client has a stronger capability boundary. If
arbitrary browsing or embedding is added, it should run in a separate unprivileged WebView with no
native bridge.

## What Common Requests Mean Today

| Request | Current honest implementation | Missing first-class capability |
| --- | --- | --- |
| "Retrieve this document and make me a reading UI." | An operator or trusted server-side connector obtains the document first; the generator packages a bounded snapshot or derived text locally. | A governed document-retrieval connector, MIME validation, size limits, provenance, and refresh controls. |
| "Show the current state of my 3D print." | A supplied status snapshot can be rendered. The generated surface must not imply that it is live. | A printer connector and a server-owned event stream with authentication, reconnect, stale-data, and offline behavior. |
| "Show me the price of Bitcoin." | A price supplied with the generation request can be displayed with its timestamp. | A market-data connector with provider policy, caching, rate limits, timestamping, and update delivery. |
| "Use this image, font, model, or audio file." | The asset must already be included in the generated bundle. | A server-side asset importer that downloads, validates, hash-pins, and vendors the asset. |
| "Load Three.js from a CDN." | Not allowed; ship a pinned local copy. | A curated dependency registry or server-side package importer. |

## Intended Capability Model

External capability should be introduced in layers rather than with a single "allow network" flag.

### 1. Vendored Assets

The agent server should be able to import passive assets and approved libraries before packaging.
Imports should use HTTPS, block private and metadata addresses, limit redirects and bytes, validate
declared and detected MIME types, reject active SVG/HTML where inappropriate, record source and
license metadata, pin a content hash, and rewrite the surface to a local bundle path.

This preserves immutable, offline-capable surfaces while allowing the generator to use the broader
asset ecosystem.

### 2. Server-Owned Data Connectors

Live documents, printer telemetry, market prices, and similar data should normally enter through
the laptop server. Credentials remain on the server. A connector normalizes snapshots and events,
applies rate limits and caching, records freshness, and exposes a narrow authenticated channel to
the target device. The surface consumes that channel rather than holding third-party credentials or
calling arbitrary origins directly.

### 3. Manifest-Declared Network Policy

A future surface manifest should declare one of these modes explicitly:

- `none`: no runtime network access beyond the container runtime;
- `server-data`: access only to named server-owned data channels;
- `direct-allowlist`: HTTPS access to narrowly declared public origins and methods;
- `untrusted-web`: separate bridge-free browsing context, never the privileged surface WebView.

The Android client must enforce the selected mode in request interception and navigation handling.
The server validator should then verify the declaration and generated source against the same
policy. Static regex checks alone are insufficient.

## Design Principle

Self-contained bundles should remain the safe default, not the only useful mode. The system should
make external data and assets deliberate, inspectable, and reproducible without preventing agents
from building genuinely connected interfaces.
