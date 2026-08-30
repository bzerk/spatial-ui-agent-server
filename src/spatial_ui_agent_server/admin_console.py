from __future__ import annotations

import json
from pathlib import Path


def render_admin_console(csrf_token: str) -> str:
    return ADMIN_CONSOLE.replace("__CSRF_TOKEN__", json.dumps(csrf_token))


def read_log_tail(path: Path, max_bytes: int = 128 * 1024) -> str:
    if not path.exists():
        return "Log file has not been created yet."
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        handle.seek(max(0, size - max_bytes))
        payload = handle.read()
    text = payload.decode("utf-8", errors="replace")
    if size > max_bytes:
        text = text.split("\n", 1)[-1]
    return text


ADMIN_CONSOLE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Spatial UI Agent</title>
  <style>
    :root {
      color-scheme: dark;
      --ink: #e6f4e9;
      --muted: #7d9585;
      --line: #294137;
      --panel: rgba(13, 24, 19, .94);
      --panel-2: #101d17;
      --signal: #59ff8b;
      --signal-dim: #1d7f40;
      --warn: #ffc857;
      --error: #ff6b6b;
      --bg: #050806;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background:
        radial-gradient(circle at 85% 5%, rgba(35, 96, 59, .26), transparent 28rem),
        linear-gradient(rgba(89, 255, 139, .025) 1px, transparent 1px),
        linear-gradient(90deg, rgba(89, 255, 139, .025) 1px, transparent 1px),
        var(--bg);
      background-size: auto, 24px 24px, 24px 24px, auto;
      font: 13px/1.45 "SFMono-Regular", Menlo, Monaco, Consolas, monospace;
    }
    button, input, select, textarea { font: inherit; }
    .shell { width: min(1480px, calc(100% - 32px)); margin: 0 auto; padding: 22px 0 48px; }
    header {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 24px;
      padding: 8px 2px 20px;
      border-bottom: 1px solid var(--line);
    }
    .eyebrow { color: var(--signal); letter-spacing: .18em; font-size: 11px; }
    h1 { margin: 6px 0 0; font-size: clamp(23px, 3vw, 38px); font-weight: 500; letter-spacing: -.04em; }
    .health { display: flex; align-items: center; gap: 9px; color: var(--muted); white-space: nowrap; }
    .health-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--warn); box-shadow: 0 0 12px currentColor; }
    .health.online .health-dot { color: var(--signal); background: var(--signal); }
    .layout { display: grid; grid-template-columns: minmax(330px, 420px) minmax(0, 1fr); gap: 18px; margin-top: 18px; }
    .stack { display: grid; gap: 18px; align-content: start; }
    .panel { border: 1px solid var(--line); background: var(--panel); box-shadow: 0 18px 60px rgba(0, 0, 0, .24); }
    .panel-head { display: flex; justify-content: space-between; align-items: center; min-height: 43px; padding: 0 14px; border-bottom: 1px solid var(--line); color: var(--muted); letter-spacing: .1em; text-transform: uppercase; font-size: 10px; }
    .panel-body { padding: 14px; }
    label { display: block; margin: 0 0 6px; color: var(--muted); font-size: 11px; }
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 0;
      color: var(--ink);
      background: #07100b;
      padding: 10px 11px;
      outline: none;
    }
    input:focus, select:focus, textarea:focus { border-color: var(--signal-dim); box-shadow: 0 0 0 1px var(--signal-dim); }
    textarea { min-height: 122px; resize: vertical; }
    .field + .field { margin-top: 12px; }
    .actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
    button {
      min-height: 38px;
      border: 1px solid var(--line);
      color: var(--ink);
      background: #0c1711;
      cursor: pointer;
      padding: 8px 10px;
      text-align: left;
    }
    button:hover { border-color: var(--signal); color: var(--signal); }
    button:disabled { opacity: .45; cursor: wait; }
    button.primary { grid-column: 1 / -1; border-color: var(--signal-dim); color: var(--signal); background: rgba(29, 127, 64, .12); }
    .inline { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
    .metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; background: var(--line); }
    .metric { min-height: 88px; padding: 13px; background: var(--panel-2); }
    .metric b { display: block; margin-top: 8px; overflow: hidden; text-overflow: ellipsis; color: var(--signal); font-size: 17px; font-weight: 500; white-space: nowrap; }
    .metric span { color: var(--muted); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 9px 10px; border-bottom: 1px solid rgba(41, 65, 55, .72); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-size: 9px; letter-spacing: .1em; text-transform: uppercase; }
    td { font-size: 11px; }
    tr:last-child td { border-bottom: 0; }
    .status-ready, .status-rendered, .status-loaded { color: var(--signal); }
    .status-failed { color: var(--error); }
    .status-designing, .status-transcribing, .status-checking { color: var(--warn); }
    .muted { color: var(--muted); }
    .mono-cut { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    pre {
      height: 300px;
      margin: 0;
      overflow: auto;
      padding: 13px;
      color: #a9cbb5;
      background: #020403;
      font: 10px/1.5 "SFMono-Regular", Menlo, Monaco, Consolas, monospace;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .toast { min-height: 20px; margin-top: 10px; color: var(--muted); }
    .toast.error { color: var(--error); }
    .toast.ok { color: var(--signal); }
    .empty { padding: 16px 10px; color: var(--muted); }
    @media (max-width: 900px) {
      .layout { grid-template-columns: 1fr; }
      .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div><div class="eyebrow">LOCAL ROKID RUNTIME</div><h1>Spatial UI Agent</h1></div>
      <div id="health" class="health"><span class="health-dot"></span><span>connecting</span></div>
    </header>

    <div class="layout">
      <div class="stack">
        <section class="panel">
          <div class="panel-head"><span>Command deck</span><span>loopback only</span></div>
          <div class="panel-body">
            <div class="field"><label for="device">Target glasses</label><select id="device"></select></div>
            <div class="field"><label for="prompt">Generate or revise the active surface</label><textarea id="prompt" placeholder="Make the starfield denser and double yaw sensitivity..."></textarea></div>
            <div class="actions">
              <button id="generate" class="primary">GENERATE + PUSH</button>
              <button data-action="push-active">PUSH ACTIVE</button>
              <button data-action="reset-constellation">RESET DEFAULT</button>
              <button data-action="reset-brick-breaker">BRICK BREAKER</button>
              <button data-action="capture-camera">CAPTURE CAMERA</button>
              <button data-action="capture-display">CAPTURE DISPLAY</button>
            </div>
            <div class="field"><label for="speech">Speak on glasses</label><div class="inline"><input id="speech" maxlength="1000" placeholder="The new surface is ready."><button id="speak">SPEAK</button></div></div>
            <div id="toast" class="toast">Ready.</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><span>Recent generation jobs</span><span id="job-count">0</span></div>
          <div id="jobs" class="table-wrap"></div>
        </section>
      </div>

      <div class="stack">
        <section class="panel">
          <div class="metric-grid">
            <div class="metric"><span>Connected devices</span><b id="metric-devices">0</b></div>
            <div class="metric"><span>Active revision</span><b id="metric-revision">none</b></div>
            <div class="metric"><span>Transcriber</span><b id="metric-transcriber">unknown</b></div>
            <div class="metric"><span>Latest ack</span><b id="metric-ack">none</b></div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><span>Delivery and acknowledgements</span><span>live</span></div>
          <div id="events" class="table-wrap"></div>
        </section>

        <section class="panel">
          <div class="panel-head"><span>Voice turns</span><span>local media</span></div>
          <div id="turns" class="table-wrap"></div>
        </section>

        <section class="panel">
          <div class="panel-head"><span>Server log</span><span id="log-path">rotating</span></div>
          <pre id="logs">Waiting for log stream...</pre>
        </section>
      </div>
    </div>
  </main>
  <script>
    const csrfToken = __CSRF_TOKEN__;
    let selectedDevice = "";
    const byId = id => document.getElementById(id);
    const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
    const short = value => value ? String(value).slice(0, 12) : "none";
    const statusClass = value => `status-${String(value || "").toLowerCase().replace(/[^a-z-]/g, "")}`;
    const table = (heads, rows, empty) => rows.length
      ? `<table><thead><tr>${heads.map(head => `<th>${escapeHtml(head)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`
      : `<div class="empty">${escapeHtml(empty)}</div>`;

    function setToast(message, kind = "") {
      const node = byId("toast");
      node.textContent = message;
      node.className = `toast ${kind}`;
    }

    function currentDevice() {
      return byId("device").value;
    }

    async function sendAction(action, payload = {}) {
      const response = await fetch("/admin/actions", {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken},
        body: JSON.stringify({action, device_id: currentDevice(), ...payload})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
      return result;
    }

    async function invoke(action, payload = {}) {
      document.querySelectorAll("button").forEach(button => button.disabled = true);
      setToast(`${action.replaceAll("-", " ")} queued...`);
      try {
        const result = await sendAction(action, payload);
        setToast(result.message || "Command queued.", "ok");
        await refreshState();
      } catch (error) {
        setToast(error.message, "error");
      } finally {
        document.querySelectorAll("button").forEach(button => button.disabled = false);
      }
    }

    function renderState(state) {
      const health = byId("health");
      health.className = "health online";
      health.querySelector("span:last-child").textContent = `online · ${state.port}`;

      const select = byId("device");
      selectedDevice = select.value || selectedDevice;
      select.innerHTML = state.devices.length
        ? state.devices.map(device => `<option value="${escapeHtml(device.id)}">${escapeHtml(device.id)} · ${escapeHtml(device.last_seen.slice(11, 19))}</option>`).join("")
        : '<option value="">No glasses seen</option>';
      if (state.devices.some(device => device.id === selectedDevice)) select.value = selectedDevice;
      selectedDevice = select.value;

      byId("metric-devices").textContent = state.devices.length;
      byId("metric-revision").textContent = short(state.active_surface);
      byId("metric-transcriber").textContent = state.transcriber.status;
      byId("metric-ack").textContent = state.acknowledgements[0]?.status || "none";
      byId("log-path").textContent = state.log_file;

      const eventRows = state.events.map(item => `<tr><td>${item.seq}</td><td>${escapeHtml(item.kind)}</td><td class="mono-cut">${escapeHtml(item.device_id)}</td><td>${escapeHtml(item.ack_status || "pending")}</td><td>${escapeHtml(item.created_at.slice(11, 19))}</td></tr>`);
      byId("events").innerHTML = table(["Seq", "Event", "Device", "Ack", "UTC"], eventRows, "No delivery events yet.");

      const turnRows = state.turns.map(item => `<tr><td class="mono-cut">${escapeHtml(short(item.id))}</td><td class="${statusClass(item.status)}">${escapeHtml(item.status)}</td><td class="mono-cut" title="${escapeHtml(item.transcript || item.error || "")}">${escapeHtml(item.transcript || item.error || "—")}</td><td>${escapeHtml(item.updated_at.slice(11, 19))}</td></tr>`);
      byId("turns").innerHTML = table(["Turn", "Status", "Transcript / error", "UTC"], turnRows, "No voice turns yet.");

      const jobRows = state.jobs.map(item => `<tr><td>${escapeHtml(short(item.id))}</td><td class="${statusClass(item.status)}">${escapeHtml(item.status)}</td><td class="mono-cut" title="${escapeHtml(item.request)}">${escapeHtml(item.request)}</td></tr>`);
      byId("jobs").innerHTML = table(["Job", "Status", "Request"], jobRows, "No console jobs this process.");
      byId("job-count").textContent = state.jobs.length;
    }

    async function refreshState() {
      try {
        const [stateResponse, logResponse] = await Promise.all([
          fetch("/admin/state", {cache: "no-store"}),
          fetch("/admin/logs", {cache: "no-store"})
        ]);
        if (!stateResponse.ok || !logResponse.ok) throw new Error("operator endpoint unavailable");
        renderState(await stateResponse.json());
        const logs = byId("logs");
        const nearBottom = logs.scrollHeight - logs.scrollTop - logs.clientHeight < 60;
        logs.textContent = await logResponse.text();
        if (nearBottom) logs.scrollTop = logs.scrollHeight;
      } catch (error) {
        const health = byId("health");
        health.className = "health";
        health.querySelector("span:last-child").textContent = "offline";
      }
    }

    document.querySelectorAll("[data-action]").forEach(button => button.addEventListener("click", () => invoke(button.dataset.action)));
    byId("generate").addEventListener("click", () => {
      const request = byId("prompt").value.trim();
      if (!request) return setToast("Enter a surface request.", "error");
      invoke("generate", {request});
    });
    byId("speak").addEventListener("click", () => {
      const text = byId("speech").value.trim();
      if (!text) return setToast("Enter speech text.", "error");
      invoke("speak", {text});
    });
    byId("device").addEventListener("change", event => selectedDevice = event.target.value);
    refreshState();
    setInterval(refreshState, 2000);
  </script>
</body>
</html>
"""
