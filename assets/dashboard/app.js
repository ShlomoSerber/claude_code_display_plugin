"use strict";
const $ = (s, r = document) => r.querySelector(s);
const api = (p, o) => fetch(p, o).then(r => r.json());

const ICON_EXPAND = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5"/></svg>';
const ICON_COLLAPSE = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v5H3M16 3v5h5M3 16h5v5M21 16h-5v5"/></svg>';

/* ---------- plugin gate ---------- */
function renderGate(state) {
  const installed = state.claude && state.claude.installed;
  const pill = $("#claudePill");
  pill.textContent = installed ? ("Claude " + (state.claude.version || "installed")) : "Claude not installed";
  pill.className = "pill " + (installed ? "ok" : "no");
  $("#gate").classList.toggle("hidden", installed);
  $("#applied").classList.toggle("hidden", !installed);
}
async function doApply(btn, out) {
  btn.disabled = true; const label = btn.textContent; btn.textContent = "Applying…";
  out.classList.remove("hidden"); out.textContent = "Running plugin registration…";
  try {
    const res = await api("/api/apply-plugin", { method: "POST" });
    out.textContent = res.message + "\n\n" + (res.steps || []).map(
      s => `$ ${s.cmd}\n[rc ${s.rc}] ${s.out || ""} ${s.err || ""}`).join("\n\n");
  } catch (e) { out.textContent = "Failed: " + e; }
  btn.disabled = false; btn.textContent = label; load();
}

/* ---------- in-window stage: fullscreen (view) and control ---------- */
let stage = { key: null, mode: null, w: 1280, h: 800 };
const stageEl = () => $("#stage");
const stageImg = $("#stageimg");

function openStage(key, mode, w, h) {
  stage = { key, mode, w: w || 1280, h: h || 800 };
  const el = stageEl();
  el.classList.remove("hidden");
  el.classList.toggle("control", mode === "control");
  $("#stagebadge").classList.toggle("hidden", mode !== "control");
  stageImg.src = `/surface/${key}/stream.mjpeg?w=1280`;
}
function closeStage() {
  if (stageEl().classList.contains("hidden")) return;
  stageEl().classList.add("hidden");
  stageImg.src = "";
  stage.key = null;
}
$("#stagetoggle").innerHTML = ICON_COLLAPSE;
$("#stagetoggle").onclick = closeStage;

function sendInput(body) {
  if (!stage.key) return;
  fetch(`/api/surface/${stage.key}/input`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
  }).catch(() => {});
}
function mapCoords(e) {
  const rect = stageImg.getBoundingClientRect();
  const scale = Math.min(rect.width / stage.w, rect.height / stage.h);
  const cw = stage.w * scale, ch = stage.h * scale;
  const ox = (rect.width - cw) / 2, oy = (rect.height - ch) / 2;
  const x = Math.round(Math.max(0, Math.min(stage.w - 1, (e.clientX - rect.left - ox) / scale)));
  const y = Math.round(Math.max(0, Math.min(stage.h - 1, (e.clientY - rect.top - oy) / scale)));
  return { x, y };
}
stageImg.addEventListener("click", e => {
  if (stage.mode !== "control") return;
  const p = mapCoords(e); sendInput({ action: "click", x: p.x, y: p.y, button: 1 });
});
stageImg.addEventListener("dblclick", e => {
  if (stage.mode !== "control") return;
  const p = mapCoords(e); sendInput({ action: "click", x: p.x, y: p.y, button: 1, double: true });
});
stageImg.addEventListener("contextmenu", e => {
  if (stage.mode !== "control") return;
  e.preventDefault(); const p = mapCoords(e); sendInput({ action: "click", x: p.x, y: p.y, button: 3 });
});
stageImg.addEventListener("wheel", e => {
  if (stage.mode !== "control") return;
  e.preventDefault(); const p = mapCoords(e);
  sendInput({ action: "scroll", x: p.x, y: p.y, amount: e.deltaY > 0 ? 3 : -3 });
}, { passive: false });

const KEYMAP = {
  Enter: "Return", Backspace: "BackSpace", Tab: "Tab", Escape: "Escape", Delete: "Delete",
  ArrowUp: "Up", ArrowDown: "Down", ArrowLeft: "Left", ArrowRight: "Right",
  Home: "Home", End: "End", PageUp: "Prior", PageDown: "Next", " ": "space"
};
document.addEventListener("keydown", e => {
  if (stageEl().classList.contains("hidden")) return;
  if (stage.mode !== "control") { if (e.key === "Escape") closeStage(); return; }
  const mods = [];
  if (e.ctrlKey) mods.push("ctrl");
  if (e.altKey) mods.push("alt");
  if (e.metaKey) mods.push("super");
  const special = KEYMAP[e.key];
  if (special || mods.length) {
    const base = special || (e.key.length === 1 ? e.key : null);
    if (!base) return;
    e.preventDefault();
    sendInput({ action: "key", keys: [...mods, base].join("+") });
  } else if (e.key.length === 1) {
    e.preventDefault();
    sendInput({ action: "type", text: e.key });
  }
});

/* ---------- displays ---------- */
const tiles = new Map();
function renderSurfaces(state) {
  const grid = $("#grid");
  const seen = new Set();
  const live = state.surfaces.filter(s => s.alive);
  $("#empty").classList.toggle("hidden", live.length > 0);
  $("#bugcount").textContent = state.bugs ? (state.bugs + " bug report(s) recorded") : "";

  for (const s of live) {
    seen.add(s.key);
    let t = tiles.get(s.key);
    if (!t) {
      const frag = $("#tile").content.cloneNode(true);
      t = frag.querySelector(".tile");
      t.querySelector(".stream").src = `/surface/${s.key}/stream.mjpeg`;
      t.querySelector(".expand").innerHTML = ICON_EXPAND;
      t.querySelector(".expand").onclick = () => openStage(t.dataset.key, "view", +t.dataset.w, +t.dataset.h);
      t.querySelector(".control").onclick = () => openStage(t.dataset.key, "control", +t.dataset.w, +t.dataset.h);
      t.querySelector(".close").onclick = async () => {
        await api(`/api/surface/${s.key}/close`, { method: "POST" }); load();
      };
      tiles.set(s.key, t);
      grid.appendChild(t);
    }
    t.dataset.key = s.key; t.dataset.w = s.width; t.dataset.h = s.height;
    t.querySelector(".dpy").textContent = s.display;
    t.querySelector(".pss").textContent = s.pss_mb + " MB";
    t.querySelector(".path").textContent = s.project_dir || "";
  }
  for (const [key, t] of tiles) {
    if (!seen.has(key)) { t.remove(); tiles.delete(key); }
  }
}

async function load() {
  try {
    const state = await api("/api/state");
    renderGate(state);
    renderSurfaces(state);
  } catch (e) { /* server not ready */ }
}

$("#applyBtn").onclick = () => doApply($("#applyBtn"), $("#applyOut"));
$("#applyBtn2").onclick = () => doApply($("#applyBtn2"), $("#applyOut2"));
load();
setInterval(load, 4000);
