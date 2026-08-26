"use strict";
const $ = (s, r = document) => r.querySelector(s);
const api = (p, o) => fetch(p, o).then(r => r.json());

const ICON_EXPAND = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5"/></svg>';
const ICON_COLLAPSE = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v5H3M16 3v5h5M3 16h5v5M21 16h-5v5"/></svg>';
const ICON_CHEV = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>';

// Live view via frame-polling (works in Chrome and WebKitGTK, which doesn't do MJPEG).
// Preloads the next frame off-screen and swaps on load to avoid flicker.
function makePoller(imgEl, urlFn, fps) {
  let stopped = false, timer = null;
  function tick() {
    if (stopped) return;
    const probe = new Image();
    probe.onload = () => { if (!stopped) imgEl.src = probe.src; timer = setTimeout(tick, 1000 / fps); };
    probe.onerror = () => { timer = setTimeout(tick, 1000 / fps); };
    probe.src = urlFn();
  }
  tick();
  return () => { stopped = true; if (timer) clearTimeout(timer); };
}

/* ---------- single-line status card ---------- */
function renderGate(state) {
  const g = $("#gate");
  const claude = state.claude && state.claude.installed;
  const applied = state.plugin && state.plugin.plugin_applied;
  g.classList.remove("hidden");
  if (!claude) {
    g.innerHTML = `<span class="gtxt"><b>Claude Code is not installed</b> — the display tools need it.</span>
      <span class="grow"></span>
      <a class="btn" href="https://claude.com/claude-code" target="_blank" rel="noopener">Install Claude</a>`;
  } else if (!applied) {
    g.innerHTML = `<span class="gtxt"><b>Plugin not installed</b></span>
      <span class="grow"></span>
      <button class="btn" data-act="apply">Install</button>`;
  } else {
    g.innerHTML = `<span class="gtxt"><b>Plugin installed</b> <span class="muted">· Claude ${state.claude.version || ""}</span></span>
      <span class="grow"></span>
      <button class="btn" data-act="apply">Reinstall</button>
      <button class="btn danger" data-act="remove">Uninstall</button>`;
  }
  g.querySelectorAll("[data-act]").forEach(b => { b.onclick = () => gateAction(b.dataset.act, b); });
}
async function gateAction(act, btn) {
  const w = btn.offsetWidth;
  btn.disabled = true;
  btn.style.minWidth = w + "px";           // avoid the button collapsing around the spinner
  btn.innerHTML = '<span class="spinner"></span>';
  try { await api(act === "remove" ? "/api/remove-plugin" : "/api/apply-plugin", { method: "POST" }); }
  catch (e) { /* ignore */ }
  load();                                   // rebuilds the card in its new state
}

/* ---------- in-window stage: fullscreen (view) + control (noVNC) ---------- */
const stageEl = () => $("#stage");
const stageImg = $("#stageimg");
const stageFrame = $("#stageframe");
let stageStop = null;

function openStage(key, mode, w, h) {
  const el = stageEl();
  el.classList.remove("hidden");
  if (stageStop) { stageStop(); stageStop = null; }
  if (mode === "control") {
    stageImg.classList.add("hidden"); stageImg.src = "";
    stageFrame.classList.remove("hidden");
    stageFrame.removeAttribute("src");
    api(`/api/surface/${key}/control`, { method: "POST" })
      .then(d => { if (d && d.url) stageFrame.src = d.url; })
      .catch(() => {});
  } else {
    stageFrame.classList.add("hidden"); stageFrame.removeAttribute("src");
    stageImg.classList.remove("hidden");
    stageStop = makePoller(stageImg, () => `/surface/${key}/frame.png?w=1280&t=${Date.now()}`, 4);
  }
}
function closeStage() {
  const el = stageEl();
  if (el.classList.contains("hidden")) return;
  el.classList.add("hidden");
  if (stageStop) { stageStop(); stageStop = null; }
  stageImg.src = "";
  stageFrame.removeAttribute("src");
}
$("#stagetoggle").innerHTML = ICON_COLLAPSE;
$("#stagetoggle").onclick = closeStage;
document.addEventListener("keydown", e => {
  if (!stageEl().classList.contains("hidden") && e.key === "Escape") closeStage();
});

/* ---------- displays ---------- */
const tiles = new Map();
function renderSurfaces(state) {
  const grid = $("#grid");
  const seen = new Set();
  const live = state.surfaces.filter(s => s.alive);
  $("#empty").classList.toggle("hidden", live.length > 0);

  for (const s of live) {
    seen.add(s.key);
    let t = tiles.get(s.key);
    if (!t) {
      const frag = $("#tile").content.cloneNode(true);
      t = frag.querySelector(".tile");
      const streamImg = t.querySelector(".stream");
      t._stopPoll = makePoller(streamImg, () => `/surface/${s.key}/frame.png?w=720&t=${Date.now()}`, 3);
      t.querySelector(".expand").innerHTML = ICON_EXPAND;
      t.querySelector(".expand").onclick = () => openStage(t.dataset.key, "view", +t.dataset.w, +t.dataset.h);
      t.querySelector(".control").onclick = () => openStage(t.dataset.key, "control", +t.dataset.w, +t.dataset.h);
      t.querySelector(".recover").onclick = async (e) => {
        const b = e.currentTarget, label = b.textContent;
        b.disabled = true; b.style.minWidth = b.offsetWidth + "px";
        b.innerHTML = '<span class="spinner"></span>';
        try { await api(`/api/surface/${t.dataset.key}/recover`, { method: "POST", body: "{}" }); }
        catch (err) { /* ignore */ }
        b.disabled = false; b.textContent = label;
      };
      t.querySelector(".close").onclick = async () => {
        await api(`/api/surface/${s.key}/close`, { method: "POST" }); load();
      };
      tiles.set(s.key, t);
      grid.appendChild(t);
    }
    t.dataset.key = s.key; t.dataset.w = s.width; t.dataset.h = s.height;
    t.querySelector(".dpy").textContent = `${s.display}  ${s.key}`;
    const tag = t.querySelector(".tag");
    tag.textContent = s.label || "";
    tag.classList.toggle("hidden", !s.label);
    t.querySelector(".pss").textContent = s.pss_mb + " MB";
    t.querySelector(".path").textContent = s.project_dir || "";
    t.querySelector(".url").textContent = s.url || "about:blank";
  }
  for (const [key, t] of tiles) {
    if (!seen.has(key)) { if (t._stopPoll) t._stopPoll(); t.remove(); tiles.delete(key); }
  }
}

/* ---------- reports: what sessions filed back (bugs + feedback) ---------- */
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let reportsOpen = false;

function reportCard(r) {
  const bug = r.kind === "bug";
  const tag = bug ? (r.severity || "normal") : (r.category || "other").replace("_", " ");
  const where = (r.project_dir || "").split("/").filter(Boolean).pop() || "";
  const meta = [r.created_iso || "", where, r.version ? "v" + r.version : ""].filter(Boolean);
  return `<article class="rpt">
    <div class="rtop">
      <span class="badge ${bug ? "bug" : "fb"}">${bug ? "Bug" : "Feedback"}</span>
      <span class="badge soft">${esc(tag)}</span>
      <span class="grow"></span>
      <button class="btn sm" data-kind="${esc(r.kind)}" data-id="${esc(r.id)}">Dismiss</button>
    </div>
    <p class="rsum">${esc(r.summary)}</p>
    ${r.details ? `<details><summary class="muted">Details</summary><pre>${esc(r.details)}</pre></details>` : ""}
    <div class="rmeta muted">${esc(meta.join(" · "))}</div>
  </article>`;
}

async function loadReports() {
  const list = $("#rlist");
  try {
    const d = await api("/api/reports");
    const items = (d && d.reports) || [];
    list.innerHTML = items.length
      ? items.map(reportCard).join("")
      : `<p class="muted">Nothing filed yet. Sessions can call <code>record_bug</code> when a display
         tool breaks and <code>record_feedback</code> to suggest improvements.</p>`;
    list.querySelectorAll("button[data-id]").forEach(b => {
      b.onclick = async () => {
        b.disabled = true;
        await api(`/api/reports/${b.dataset.kind}/${b.dataset.id}/archive`, { method: "POST" });
        loadReports(); load();
      };
    });
  } catch (e) { /* server not ready */ }
}

$("#rtoggle .chev").innerHTML = ICON_CHEV;      // points down when closed, up when open
$("#rtoggle").onclick = () => {
  reportsOpen = !reportsOpen;
  $("#rlist").classList.toggle("hidden", !reportsOpen);
  $("#rtoggle").classList.toggle("open", reportsOpen);
  $("#rtoggle").setAttribute("aria-expanded", String(reportsOpen));
  if (reportsOpen) loadReports();
};

let reportSig = "";
function renderReportCount(state) {
  const c = (state && state.reports) || {};
  const parts = [];
  if (c.bug) parts.push(c.bug + (c.bug === 1 ? " bug report" : " bug reports"));
  if (c.feedback) parts.push(c.feedback + " feedback");
  $("#rcount").textContent = parts.length ? parts.join(" · ") : "nothing filed";
  const sig = `${c.bug || 0}/${c.feedback || 0}`;          // only redraw when something arrived,
  if (reportsOpen && sig !== reportSig) loadReports();      // so open details stay open
  reportSig = sig;
}

async function load() {
  try {
    const state = await api("/api/state");
    renderGate(state);
    renderSurfaces(state);
    renderReportCount(state);
  } catch (e) { /* server not ready */ }
}
load();
setInterval(load, 4000);
