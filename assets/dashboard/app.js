"use strict";
const $ = (s, r = document) => r.querySelector(s);

async function api(path, opts) {
  const r = await fetch(path, opts);
  return r.json();
}

function renderGate(state) {
  const installed = state.claude && state.claude.installed;
  const pill = $("#claudePill");
  pill.textContent = installed ? ("Claude " + (state.claude.version || "installed")) : "Claude not installed";
  pill.className = "pill " + (installed ? "ok" : "no");
  $("#gate").classList.toggle("hidden", installed);
  $("#applied").classList.toggle("hidden", !installed);
}

async function doApply(btn, out) {
  btn.disabled = true; btn.textContent = "Applying…";
  out.classList.remove("hidden");
  out.textContent = "Running plugin registration…";
  try {
    const res = await api("/api/apply-plugin", { method: "POST" });
    out.textContent = res.message + "\n\n" + (res.steps || []).map(
      s => `$ ${s.cmd}\n[rc ${s.rc}] ${s.out || ""} ${s.err || ""}`).join("\n\n");
  } catch (e) {
    out.textContent = "Failed: " + e;
  }
  btn.disabled = false; btn.textContent = "Apply plugin";
  load();
}

// ---- fullscreen (view-only) ----
function openFullscreen(key, display, path) {
  const fs = $("#fs");
  $("#fstitle").textContent = display + (path ? "  ·  " + path : "");
  // request full display resolution for the fullscreen view
  $("#fsimg").src = `/surface/${key}/stream.mjpeg?w=1280`;
  fs.classList.remove("hidden");
  if (fs.requestFullscreen) fs.requestFullscreen().catch(() => {});
}
function closeFullscreen() {
  const fs = $("#fs");
  if (fs.classList.contains("hidden")) return;
  $("#fsimg").src = "";           // stop the stream so the server frees the thread
  fs.classList.add("hidden");
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
}
$("#fsclose").onclick = closeFullscreen;
document.addEventListener("fullscreenchange", () => {
  if (!document.fullscreenElement) closeFullscreen();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeFullscreen(); });

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
      t.querySelector(".expand").onclick = () => openFullscreen(
        s.key, t.querySelector(".dpy").textContent, t.querySelector(".path").textContent);
      t.querySelector(".close").onclick = async () => {
        await api(`/api/surface/${s.key}/close`, { method: "POST" }); load();
      };
      t.querySelector(".vnc").onclick = async () => {
        const r = await api(`/api/surface/${s.key}/vnc`, { method: "POST" });
        const info = t.querySelector(".vncinfo");
        info.classList.remove("hidden");
        info.textContent = r.port
          ? `VNC ready on localhost:${r.port} — connect a viewer (e.g. vncviewer localhost:${r.port}) to take control.`
          : "Could not start VNC.";
      };
      tiles.set(s.key, t);
      grid.appendChild(t);
    }
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
