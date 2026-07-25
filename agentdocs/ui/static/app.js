"use strict";

/* ------------------------------------------------------------------ *
 *  AgentDocs UI — vanilla JS, no build step.
 * ------------------------------------------------------------------ */

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  root: "",
  docsets: [],
  selected: null,      // {path, name}
  models: [],
  termCwd: "",
  browsePath: "",
};

/* ---------- tiny helpers ---------- */
async function getJSON(url) {
  const r = await fetch(url);
  return r.json();
}
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
function toast(msg) {
  let t = $(".toast");
  if (!t) { t = el("div", "toast"); document.body.appendChild(t); }
  t.textContent = msg;
  requestAnimationFrame(() => t.classList.add("show"));
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), 1600);
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast("copied"); }
  catch { toast("copy failed"); }
}

/* ---------- streaming POST (SSE-over-fetch) ---------- */
async function postStream(url, body, onEvent) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (line) { try { onEvent(JSON.parse(line.slice(6))); } catch (_) {} }
    }
  }
}

/* ---------- minimal markdown renderer ---------- */
function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function inline(s) {
  s = escapeHtml(s);
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  s = s.replace(/&lt;(https?:\/\/[^\s&]+)&gt;/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
  return s;
}
function renderMarkdown(md) {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  let html = "", i = 0, srcNote = "";

  // pull a leading source comment / frontmatter out as a subtle note
  if (lines[0] && lines[0].startsWith("<!--")) {
    srcNote = lines[0].replace(/<!--|-->/g, "").trim();
    i = 1; while (lines[i] === "") i++;
  } else if (lines[0] === "---") {
    let j = 1; const fm = [];
    while (j < lines.length && lines[j] !== "---") fm.push(lines[j++]);
    srcNote = fm.join(" · ");
    i = j + 1; while (lines[i] === "") i++;
  }

  let inList = null, para = [];
  const flushPara = () => { if (para.length) { html += `<p>${inline(para.join(" "))}</p>`; para = []; } };
  const closeList = () => { if (inList) { html += `</${inList}>`; inList = null; } };

  for (; i < lines.length; i++) {
    let ln = lines[i];

    if (ln.startsWith("```")) {           // fenced code
      flushPara(); closeList();
      const buf = []; i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      html += `<pre><code>${escapeHtml(buf.join("\n"))}</code></pre>`;
      continue;
    }
    const h = ln.match(/^(#{1,4})\s+(.*)/);
    if (h) { flushPara(); closeList(); html += `<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`; continue; }
    if (/^\s*[-*]\s+/.test(ln)) {
      flushPara(); if (inList !== "ul") { closeList(); html += "<ul>"; inList = "ul"; }
      html += `<li>${inline(ln.replace(/^\s*[-*]\s+/, ""))}</li>`; continue;
    }
    if (/^\s*\d+\.\s+/.test(ln)) {
      flushPara(); if (inList !== "ol") { closeList(); html += "<ol>"; inList = "ol"; }
      html += `<li>${inline(ln.replace(/^\s*\d+\.\s+/, ""))}</li>`; continue;
    }
    if (/^\s*>\s?/.test(ln)) { flushPara(); closeList(); html += `<blockquote>${inline(ln.replace(/^\s*>\s?/, ""))}</blockquote>`; continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(ln)) { flushPara(); closeList(); html += "<hr>"; continue; }
    if (ln.trim() === "") { flushPara(); closeList(); continue; }
    if (ln.trim().startsWith("|")) {       // simple table row block
      flushPara(); closeList();
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(lines[i++]);
      i--;
      html += renderTable(rows);
      continue;
    }
    para.push(ln);
  }
  flushPara(); closeList();

  const note = srcNote ? `<p class="reader-src">${escapeHtml(srcNote)}</p>` : "";
  return note + html;
}
function renderTable(rows) {
  const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  if (rows.length < 2) return "";
  const head = cells(rows[0]);
  const bodyRows = rows.slice(2);
  let h = "<table><thead><tr>" + head.map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>";
  for (const r of bodyRows) h += "<tr>" + cells(r).map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>";
  return h + "</tbody></table>";
}

/* ================================================================== *
 *  INIT
 * ================================================================== */
async function init() {
  const env = await getJSON("/api/env");
  state.termCwd = env.project_root;
  $("#termCwd").textContent = env.project_root;
  $("#rootInput").value = env.default_docs_dir;
  state.browsePath = env.default_docs_dir;

  await refreshModels();
  await loadCommands();

  bindEvents();

  // auto-load default docs dir if it exists
  if (env.default_docs_dir && env.default_docs_dir !== env.project_root) {
    loadRoot(env.default_docs_dir);
  }
}

async function refreshModels() {
  const data = await getJSON("/api/models");
  state.models = data.models || [];
  const chip = $("#ollamaChip");
  const sel = $("#modelSelect");
  sel.innerHTML = "";
  if (data.up && state.models.length) {
    chip.className = "chip up"; chip.innerHTML = `<i class="dot"></i> Ollama · ${state.models.length} models`;
    for (const m of state.models) {
      const o = el("option", null, m.parameter_size ? `${m.name}  ·  ${m.parameter_size}` : m.name);
      o.value = m.name; sel.appendChild(o);
    }
  } else {
    chip.className = "chip down"; chip.innerHTML = `<i class="dot"></i> Ollama offline`;
    const o = el("option", null, "no models — is Ollama running?"); o.value = ""; sel.appendChild(o);
  }
  updateBlueprintButton();
}

async function loadCommands() {
  const { commands } = await getJSON("/api/commands");
  const list = $("#commandList"); list.innerHTML = "";
  for (const c of commands) {
    const card = el("div", "command");
    card.innerHTML = `
      <div class="c-title"></div>
      <div class="c-actions">
        <button class="btn small btn-ghost c-copy">copy</button>
        <button class="btn small btn-ink c-run">run</button>
      </div>
      <div class="c-desc"></div>
      <div class="c-cmd"></div>`;
    $(".c-title", card).textContent = c.title;
    $(".c-desc", card).textContent = c.desc;
    $(".c-cmd", card).textContent = c.cmd;
    $(".c-copy", card).onclick = () => copyText(c.cmd);
    $(".c-run", card).onclick = () => { $("#termInput").value = c.cmd; runTerminal(); };
    list.appendChild(card);
  }
}

/* ================================================================== *
 *  FOLDER LOADING + BROWSER
 * ================================================================== */
async function loadRoot(path) {
  const data = await getJSON("/api/list?path=" + encodeURIComponent(path));
  if (data.error) { toast(data.error); return; }
  state.root = data.path;
  $("#rootInput").value = data.path;
  $("#rootChip").textContent = data.path.split(/[\\/]/).pop() || data.path;
  $("#rootChip").className = "chip";
  // terminal follows the loaded folder
  state.termCwd = data.path; $("#termCwd").textContent = data.path;

  const sets = [];
  if (data.direct_md) sets.push({ name: data.path.split(/[\\/]/).pop(), path: data.path, md_count: null, self: true });
  for (const d of data.dirs) if (d.md_count > 0) sets.push(d);
  state.docsets = sets;
  renderDocsets();
  $("#browser").classList.add("hidden");
}

function renderDocsets() {
  const list = $("#docsetList"); list.innerHTML = "";
  $("#docsetCount").textContent = state.docsets.length ? `(${state.docsets.length})` : "";
  if (!state.docsets.length) {
    list.appendChild(el("p", "empty-hint", "No documentation (.md) folders found here."));
    return;
  }
  for (const ds of state.docsets) {
    const card = el("div", "docset");
    card.innerHTML = `<div class="ds-name"></div><div class="ds-meta"></div>`;
    $(".ds-name", card).textContent = ds.name;
    const meta = $(".ds-meta", card);
    if (ds.md_count != null) meta.appendChild(el("span", "ds-tag", `${ds.md_count} pages`));
    else meta.appendChild(el("span", "ds-tag", "folder"));
    card.onclick = () => selectDocset(ds, card);
    list.appendChild(card);
    ds._card = card;
  }
}

async function selectDocset(ds) {
  state.selected = ds;
  $$(".docset").forEach((c) => c.classList.remove("active"));
  if (ds._card) ds._card.classList.add("active");

  const data = await getJSON("/api/docset?path=" + encodeURIComponent(ds.path));
  renderFileTree(data);
  // blueprint tab context
  $("#bpTitle").textContent = `Blueprint — ${data.name}`;
  $("#bpSubtitle").textContent = data.has_blueprint
    ? "A blueprint already exists for this doc set. Regenerate to overwrite, or preview the files."
    : `Turn the ${data.files.length} pages in “${data.name}” into a functional spec an AI can build from.`;
  renderBlueprintFiles(data.blueprint || []);
  updateDocsetTag(ds, data.has_blueprint);
  updateBlueprintButton();
  // terminal cwd -> docset
  state.termCwd = ds.path; $("#termCwd").textContent = ds.path;
}

function updateDocsetTag(ds, hasBp) {
  if (!ds._card || !hasBp) return;
  const meta = $(".ds-meta", ds._card);
  if (!$(".ds-tag.bp", meta)) meta.appendChild(el("span", "ds-tag bp", "blueprint"));
}

function renderFileTree(data) {
  const tree = $("#fileTree"); tree.innerHTML = "";
  if (!data.files.length) { tree.appendChild(el("p", "empty-hint", "No pages in this folder.")); return; }
  const groups = {};
  for (const f of data.files) {
    const top = f.rel.includes("/") ? f.rel.split("/")[0] : "·";
    (groups[top] ||= []).push(f);
  }
  for (const g of Object.keys(groups).sort()) {
    const grp = el("div", "ft-group");
    grp.appendChild(el("div", "ft-label", g === "·" ? "top level" : g));
    for (const f of groups[g]) {
      const name = f.rel.includes("/") ? f.rel.split("/").slice(1).join("/") : f.rel;
      const item = el("div", "ft-file", name.replace(/\.md$/, ""));
      item.title = f.rel;
      item.onclick = () => openInReader(f.path, item);
      grp.appendChild(item);
    }
    tree.appendChild(grp);
  }
}

async function openInReader(path, item) {
  $$(".ft-file").forEach((f) => f.classList.remove("active"));
  if (item) item.classList.add("active");
  const data = await getJSON("/api/file?path=" + encodeURIComponent(path));
  const reader = $("#reader");
  if (data.error) { reader.innerHTML = `<p class="empty-hint">${data.error}</p>`; return; }
  reader.innerHTML = `<div class="markdown">${renderMarkdown(data.content)}</div>`;
  reader.scrollTop = 0;
}

/* ---- filesystem browser ---- */
async function openBrowser(path) {
  const b = $("#browser");
  b.classList.remove("hidden");
  const data = await getJSON("/api/list?path=" + encodeURIComponent(path || state.browsePath || state.root));
  if (data.error) { b.innerHTML = `<div class="b-row up">${data.error}</div>`; return; }
  state.browsePath = data.path;
  b.innerHTML = "";
  const head = el("div", "b-row up");
  head.innerHTML = `<span class="b-name">📁 ${data.path}</span>`;
  const use = el("button", "b-badge"); use.textContent = "load ✓";
  use.onclick = (e) => { e.stopPropagation(); loadRoot(data.path); };
  head.appendChild(use);
  b.appendChild(head);

  if (data.parent) {
    const up = el("div", "b-row up"); up.innerHTML = `<span class="b-name">.. up one level</span>`;
    up.onclick = () => openBrowser(data.parent); b.appendChild(up);
  }
  for (const d of data.dirs) {
    const row = el("div", "b-row");
    row.innerHTML = `<span class="b-name">${d.name}</span>`;
    if (d.md_count > 0) row.appendChild(el("span", "b-badge", `${d.md_count} md`));
    row.onclick = () => openBrowser(d.path);
    b.appendChild(row);
  }
}

/* ================================================================== *
 *  BLUEPRINT
 * ================================================================== */
function updateBlueprintButton() {
  const ok = state.selected && $("#modelSelect").value && state.models.length;
  $("#bpRunBtn").disabled = !ok;
}

function renderBlueprintFiles(files) {
  const list = $("#bpFileList"); list.innerHTML = "";
  if (!files.length) {
    list.appendChild(el("p", "empty-hint", "Generated spec files will appear here. Click any to preview."));
    return;
  }
  for (const f of files) {
    const row = el("div", "bp-file");
    row.innerHTML = `<span class="fx">▤</span><span class="fn"></span>`;
    $(".fn", row).textContent = f.name;
    row.onclick = () => previewFile(f.path, f.name);
    list.appendChild(row);
  }
}

let bpBusy = false;
async function runBlueprint() {
  if (bpBusy || !state.selected) return;
  const model = $("#modelSelect").value;
  if (!model) { toast("no model selected"); return; }
  bpBusy = true;
  const btn = $("#bpRunBtn"); btn.disabled = true; const label = btn.textContent; btn.textContent = "Generating…";

  const stream = $("#bpStream"); stream.textContent = "";
  const progress = $("#bpProgress"); progress.innerHTML = "";
  const bar = el("div", "bp-bar"); const barFill = el("i"); bar.appendChild(barFill);
  const stepLine = el("div", "bp-step"); stepLine.innerHTML = `<span class="tick">◔</span><span class="lbl">starting…</span>`;
  progress.appendChild(stepLine); progress.appendChild(bar);
  const doneFiles = [];

  await postStream("/api/blueprint", { path: state.selected.path, model }, (ev) => {
    if (ev.type === "status") {
      $(".lbl", stepLine).textContent = ev.message;
      $(".tick", stepLine).textContent = "◔";
      barFill.style.width = Math.round(((ev.step - 1) / ev.total) * 100) + "%";
      stream.textContent += `\n\n─── ${ev.message} ───\n`;
      stream.scrollTop = stream.scrollHeight;
    } else if (ev.type === "token") {
      stream.textContent += ev.text;
      stream.scrollTop = stream.scrollHeight;
    } else if (ev.type === "file") {
      doneFiles.push({ name: ev.name, path: ev.path });
      renderBlueprintFiles(doneFiles);
    } else if (ev.type === "error") {
      stream.textContent += `\n\n[error] ${ev.message}\n`;
      stepLine.classList.add("done"); $(".tick", stepLine).textContent = "✕";
      toast("blueprint failed");
    } else if (ev.type === "done") {
      barFill.style.width = "100%";
      stepLine.classList.add("done"); $(".tick", stepLine).textContent = "✓";
      $(".lbl", stepLine).textContent = `Done — ${ev.files} spec file(s) written`;
      toast("blueprint ready");
    }
  });

  bpBusy = false; btn.textContent = label; updateBlueprintButton();
  if (state.selected) selectDocset(state.selected); // refresh files + tag
}

async function previewFile(path, name) {
  const data = await getJSON("/api/file?path=" + encodeURIComponent(path));
  if (data.error) { toast(data.error); return; }
  $("#modalTitle").textContent = name || data.name;
  $("#modalBody").innerHTML = renderMarkdown(data.content);
  $("#modalCopy").onclick = () => copyText(data.content);
  $("#modal").classList.remove("hidden");
}

/* ================================================================== *
 *  MINI TERMINAL
 * ================================================================== */
let termBusy = false;
function termWrite(text, cls) {
  const out = $("#termOut");
  const span = document.createElement("span");
  if (cls) span.className = cls;
  span.textContent = text + "\n";
  out.appendChild(span);
  out.scrollTop = out.scrollHeight;
}
async function runTerminal() {
  if (termBusy) { toast("a command is already running"); return; }
  const input = $("#termInput");
  const cmd = input.value.trim();
  if (!cmd) return;
  termBusy = true;
  termWrite(`› ${cmd}`, "sys");
  input.value = "";
  // make sure the drawer is visible
  $("#terminalBody").classList.remove("collapsed"); $("#termToggle").textContent = "hide";

  await postStream("/api/run", { cmd, cwd: state.termCwd }, (ev) => {
    if (ev.type === "meta") { $("#termCwd").textContent = ev.cwd; }
    else if (ev.type === "line") { termWrite(ev.text, /error|traceback|! skipped|failed/i.test(ev.text) ? "err" : null); }
    else if (ev.type === "done") { termWrite(`[exit ${ev.code}]`, "sys"); }
  });
  termBusy = false;
}

/* ================================================================== *
 *  EVENTS
 * ================================================================== */
function bindEvents() {
  $("#loadBtn").onclick = () => loadRoot($("#rootInput").value.trim());
  $("#rootInput").addEventListener("keydown", (e) => { if (e.key === "Enter") loadRoot($("#rootInput").value.trim()); });
  $("#browseBtn").onclick = () => {
    const b = $("#browser");
    if (b.classList.contains("hidden")) openBrowser($("#rootInput").value.trim() || state.root);
    else b.classList.add("hidden");
  };

  $$(".tab").forEach((t) => t.onclick = () => {
    $$(".tab").forEach((x) => x.classList.remove("active"));
    $$(".tabpane").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $(`.tabpane[data-pane="${t.dataset.tab}"]`).classList.add("active");
  });

  $("#modelSelect").onchange = updateBlueprintButton;
  $("#bpRunBtn").onclick = runBlueprint;

  $("#termRun").onclick = runTerminal;
  $("#termInput").addEventListener("keydown", (e) => { if (e.key === "Enter") runTerminal(); });
  $("#termClear").onclick = () => { $("#termOut").innerHTML = ""; };
  $("#termToggle").onclick = () => {
    const body = $("#terminalBody"); const hidden = body.classList.toggle("collapsed");
    $("#termToggle").textContent = hidden ? "show" : "hide";
  };

  $("#modalClose").onclick = () => $("#modal").classList.add("hidden");
  $("#modal").addEventListener("click", (e) => { if (e.target === $("#modal")) $("#modal").classList.add("hidden"); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#modal").classList.add("hidden"); });
}

init();
