/* Flow KB - vanilla JS canvas (no dependencies), served by the FastHTML app in main.py. Data Strategy Limited. */
'use strict';

const S = {
  schema: null, projects: [], project: null,
  nodes: new Map(), edges: new Map(), els: new Map(),
  sel: null,                 // {kind:'node'|'edge', id}
  view: { x: 60, y: 40, k: 1 },
  expanded: new Set(),
  timers: new Map(),         // node id -> debounce timer
  inflight: 0, failed: false,
};
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
const canvas = $('#canvas'), world = $('#world'), nodeLayer = $('#nodeLayer'), edgeLayer = $('#edgeLayer'), tempEdge = $('#tempEdge');
const SVGNS = 'http://www.w3.org/2000/svg';

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'value') e.value = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
function svg(tag, attrs) { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v); return e; }
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const T = t => S.schema.node_types[t];

/* ---------------- API & save status ---------------- */
function setStatus() {
  const el = $('#saveStatus');
  const pending = S.inflight + S.timers.size;
  if (S.failed) { el.className = 'status error'; el.textContent = 'Save failed – check server'; }
  else if (pending) { el.className = 'status saving'; el.textContent = 'Saving…'; }
  else { el.className = 'status ok'; el.textContent = '✓ Saved'; }
}
async function api(method, url, body, opts) {
  S.inflight++; setStatus();
  try {
    const r = await fetch(url, Object.assign({
      method, headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }, opts || {}));
    if (r.status === 401) { location.href = '/login'; throw Object.assign(new Error('Session expired - please log in again'), { status: 401 }); }
    const ct = r.headers.get('content-type') || '';
    const data = ct.includes('json') ? await r.json() : await r.text();
    if (!r.ok) { const err = new Error((data && data.error) || r.statusText); err.status = r.status; throw err; }
    S.failed = false;
    return data;
  } catch (e) {
    if (!e.status) S.failed = true;
    throw e;
  } finally { S.inflight--; setStatus(); }
}
function toast(msg, isErr) {
  const t = $('#toast'); t.textContent = msg; t.className = isErr ? 'err' : ''; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, isErr ? 5000 : 2200);
}
const fail = e => toast(e.message || String(e), true);

function scheduleNodeSave(id, delay) {
  clearTimeout(S.timers.get(id));
  S.timers.set(id, setTimeout(() => flushNode(id), delay == null ? 450 : delay));
  setStatus();
}
async function flushNode(id, keepalive) {
  clearTimeout(S.timers.get(id)); S.timers.delete(id);
  const n = S.nodes.get(id); if (!n) { setStatus(); return; }
  try { await api('PATCH', '/api/nodes/' + id, { title: n.title, x: n.x, y: n.y, data: n.data, replace_data: true }, keepalive ? { keepalive: true } : undefined); }
  catch (e) { fail(e); }
}
function flushAll(keepalive) { for (const id of Array.from(S.timers.keys())) flushNode(id, keepalive); }
window.addEventListener('beforeunload', () => flushAll(true));
window.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flushAll(true); });

/* ---------------- Projects ---------------- */
async function loadProjects() {
  S.projects = await api('GET', '/api/projects');
  const sel = $('#projectSelect'); sel.innerHTML = '';
  const byClient = {};
  for (const p of S.projects) (byClient[p.client || '(no client)'] = byClient[p.client || '(no client)'] || []).push(p);
  for (const [client, ps] of Object.entries(byClient)) {
    const og = h('optgroup', { label: client });
    for (const p of ps) og.append(h('option', { value: p.id, text: p.name }));
    sel.append(og);
  }
  if (S.project) sel.value = S.project.id;
}
async function openProject(id, focusNodeId) {
  flushAll();
  const p = await api('GET', '/api/projects/' + id);
  S.project = p; S.nodes.clear(); S.edges.clear(); S.sel = null;
  p.nodes.forEach(n => S.nodes.set(n.id, n)); p.edges.forEach(e => S.edges.set(e.id, e));
  delete p.nodes; delete p.edges;
  localStorage.setItem('flowkb.lastProject', id);
  $('#projectSelect').value = id;
  document.title = p.name + ' · Flow KB';
  renderAll();
  const v = JSON.parse(localStorage.getItem('flowkb.view.' + id) || 'null');
  if (v && !focusNodeId) { S.view = v; applyView(); } else fitView();
  if (focusNodeId && S.nodes.has(focusNodeId)) { select({ kind: 'node', id: focusNodeId }); centerOn(focusNodeId); }
  else renderPanel();
}
function projectLabel(p) { return (p.client ? p.client + ' — ' : '') + p.name; }

/* ---------------- Canvas view ---------------- */
function applyView() {
  world.style.transform = `translate(${S.view.x}px,${S.view.y}px) scale(${S.view.k})`;
  $('#zoomLabel').textContent = Math.round(S.view.k * 100) + '%';
  if (S.project) { clearTimeout(applyView._t); applyView._t = setTimeout(() => localStorage.setItem('flowkb.view.' + S.project.id, JSON.stringify(S.view)), 300); }
}
function toWorld(cx, cy) { const r = canvas.getBoundingClientRect(); return { x: (cx - r.left - S.view.x) / S.view.k, y: (cy - r.top - S.view.y) / S.view.k }; }
function zoomAt(factor, cx, cy) {
  const r = canvas.getBoundingClientRect();
  if (cx == null) { cx = r.left + r.width / 2; cy = r.top + r.height / 2; }
  const k = Math.min(2.5, Math.max(0.2, S.view.k * factor)); const w = toWorld(cx, cy);
  S.view.k = k; S.view.x = cx - r.left - w.x * k; S.view.y = cy - r.top - w.y * k; applyView();
}
function bounds() {
  let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
  for (const n of S.nodes.values()) { const b = box(n.id); x1 = Math.min(x1, b.x); y1 = Math.min(y1, b.y); x2 = Math.max(x2, b.x + b.w); y2 = Math.max(y2, b.y + b.h); }
  return isFinite(x1) ? { x1, y1, x2, y2 } : null;
}
function fitView() {
  const b = bounds(), r = canvas.getBoundingClientRect();
  if (!b) { S.view = { x: 60, y: 40, k: 1 }; applyView(); return; }
  const pad = 60, k = Math.min(1.2, Math.max(0.25, Math.min((r.width - pad * 2) / (b.x2 - b.x1), (r.height - pad * 2) / (b.y2 - b.y1))));
  S.view = { k, x: (r.width - (b.x2 - b.x1) * k) / 2 - b.x1 * k, y: (r.height - (b.y2 - b.y1) * k) / 2 - b.y1 * k };
  applyView();
}
function centerOn(id) {
  const b = box(id), r = canvas.getBoundingClientRect();
  S.view.x = r.width / 2 - (b.x + b.w / 2) * S.view.k; S.view.y = r.height / 2 - (b.y + b.h / 2) * S.view.k; applyView();
}

/* ---------------- Node rendering ---------------- */
function summaryText(n) {
  const t = T(n.type), d = n.data || {};
  const parts = [];
  for (const k of t.summary) {
    let v = d[k]; if (!v) continue;
    if (k === 'manual') v = /^y/i.test(v) ? 'Manual' : (/^p/i.test(v) ? 'Partly manual' : 'Automated');
    parts.push(esc(v));
  }
  return parts.join(' · ');
}
function fieldInput(n, f, compact) {
  const d = n.data || {}, val = d[f.key] || '';
  let inp;
  if (f.kind === 'textarea') inp = h('textarea', { rows: compact ? 2 : 3, placeholder: f.placeholder || '' });
  else if (f.kind === 'select') { inp = h('select'); for (const o of f.options) inp.append(h('option', { value: o, text: o || '—' })); }
  else inp = h('input', { type: f.kind === 'email' ? 'email' : f.kind === 'tel' ? 'tel' : f.kind === 'date' ? 'date' : 'text', placeholder: f.placeholder || '' });
  if (f.kind === 'select' && val && !f.options.includes(val)) inp.append(h('option', { value: val, text: val }));
  inp.value = val;
  inp.dataset.key = f.key;
  inp.addEventListener('input', () => setNodeField(n.id, f.key, inp.value, inp));
  if (f.kind === 'select') inp.addEventListener('change', () => setNodeField(n.id, f.key, inp.value, inp));
  return inp;
}
function buildNode(n) {
  const t = T(n.type);
  const el = h('div', { class: `node t-${n.type}`, 'data-id': n.id });
  const exp = h('button', { class: 'expand', title: 'Show / hide fields on the node' });
  const head = h('div', { class: 'head' }, h('span', { text: t.short || t.label }), h('span', { class: 'tag' }), exp);
  const title = h('div', { class: 'title', contenteditable: 'true', spellcheck: 'false', 'data-placeholder': t.title_placeholder });
  title.textContent = n.title || '';
  title.addEventListener('input', () => {
    const node = S.nodes.get(n.id); node.title = title.textContent.replace(/\n/g, ' ');
    const pt = $('#panel [data-key="__title"]'); if (pt && document.activeElement !== pt) pt.value = node.title;
    scheduleNodeSave(n.id); requestEdges();
  });
  title.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); title.blur(); } if (e.key === 'Escape') title.blur(); });
  title.addEventListener('paste', e => { e.preventDefault(); const txt = (e.clipboardData || window.clipboardData).getData('text').replace(/\s+/g, ' '); document.execCommand('insertText', false, txt); });
  title.addEventListener('focus', () => select({ kind: 'node', id: n.id }, true));
  exp.addEventListener('click', e => { e.stopPropagation(); if (S.expanded.has(n.id)) S.expanded.delete(n.id); else S.expanded.add(n.id); refreshNode(n.id, true); });
  const handle = h('div', { class: 'handle', title: 'Drag to another node to connect' });
  el.append(head, title, h('div', { class: 'summary' }), h('div', { class: 'fields' }), handle);
  el.style.left = n.x + 'px'; el.style.top = n.y + 'px';
  el.addEventListener('pointerdown', onNodePointerDown);
  handle.addEventListener('pointerdown', onHandlePointerDown);
  el.addEventListener('dblclick', e => { if (e.target === el || e.target.classList.contains('summary')) { title.focus(); placeCaretEnd(title); } });
  S.els.set(n.id, el);
  nodeLayer.append(el);
  refreshNode(n.id, true);
  return el;
}
function placeCaretEnd(el) { const r = document.createRange(); r.selectNodeContents(el); r.collapse(false); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }
function refreshNode(id, rebuildFields) {
  const n = S.nodes.get(id), el = S.els.get(id); if (!n || !el) return;
  const t = T(n.type), d = n.data || {};
  el.style.left = n.x + 'px'; el.style.top = n.y + 'px';
  const title = $('.title', el); if (document.activeElement !== title && title.textContent !== (n.title || '')) title.textContent = n.title || '';
  const tag = $('.tag', el);
  let tagText = '';
  if (n.type === 'process' && /^y/i.test(d.manual || '')) tagText = 'manual';
  if (n.type === 'validator' && d.responsibility) tagText = d.responsibility;
  tag.textContent = tagText; tag.style.display = tagText ? '' : 'none';
  const expanded = S.expanded.has(id);
  el.classList.toggle('expanded', expanded);
  $('.expand', el).textContent = expanded ? '▾' : '▸';
  $('.summary', el).innerHTML = expanded ? '' : summaryText(n);
  const fbox = $('.fields', el);
  if (rebuildFields) {
    fbox.innerHTML = '';
    if (expanded) for (const f of t.fields) fbox.append(h('div', {}, h('label', { text: f.label }), fieldInput(n, f, true)));
  } else if (expanded) {
    for (const inp of $$('[data-key]', fbox)) if (document.activeElement !== inp) inp.value = d[inp.dataset.key] || '';
  }
  el.classList.toggle('selected', !!(S.sel && S.sel.kind === 'node' && S.sel.id === id));
}
function setNodeField(id, key, value, sourceEl) {
  const n = S.nodes.get(id); if (!n) return;
  n.data = n.data || {};
  if (value === '' || value == null) delete n.data[key]; else n.data[key] = value;
  refreshNode(id);
  // sync the side panel if the edit came from the node itself
  if (S.sel && S.sel.kind === 'node' && S.sel.id === id) {
    const p = $(`#panel [data-key="${key}"]`); if (p && p !== sourceEl && document.activeElement !== p) p.value = value;
  }
  scheduleNodeSave(id); requestEdges();
}
function renderAll() {
  nodeLayer.innerHTML = ''; S.els.clear();
  for (const n of S.nodes.values()) buildNode(n);
  renderEdges(); updateEmpty();
}
function updateEmpty() { $('#emptyHint').hidden = S.nodes.size > 0; }

/* ---------------- Edges ---------------- */
function box(id) { const n = S.nodes.get(id), el = S.els.get(id); return { x: n.x, y: n.y, w: el ? el.offsetWidth : 220, h: el ? el.offsetHeight : 72 }; }
function anchor(b, side) {
  return side === 'r' ? [b.x + b.w, b.y + b.h / 2] : side === 'l' ? [b.x, b.y + b.h / 2] : side === 't' ? [b.x + b.w / 2, b.y] : [b.x + b.w / 2, b.y + b.h];
}
function geometry(a, b) {
  const ac = [a.x + a.w / 2, a.y + a.h / 2], bc = [b.x + b.w / 2, b.y + b.h / 2];
  const dx = bc[0] - ac[0], dy = bc[1] - ac[1];
  let s1, s2;
  const hgap = dx >= 0 ? b.x - (a.x + a.w) : a.x - (b.x + b.w);
  if (hgap > 30 || Math.abs(dx) > Math.abs(dy) * 1.2) { s1 = dx >= 0 ? 'r' : 'l'; s2 = dx >= 0 ? 'l' : 'r'; }
  else { s1 = dy >= 0 ? 'b' : 't'; s2 = dy >= 0 ? 't' : 'b'; }
  const p1 = anchor(a, s1), p2 = anchor(b, s2);
  const dist = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]), off = Math.max(30, Math.min(160, dist / 2));
  const dir = { r: [1, 0], l: [-1, 0], t: [0, -1], b: [0, 1] };
  const c1 = [p1[0] + dir[s1][0] * off, p1[1] + dir[s1][1] * off], c2 = [p2[0] + dir[s2][0] * off, p2[1] + dir[s2][1] * off];
  const mid = [(p1[0] + 3 * c1[0] + 3 * c2[0] + p2[0]) / 8, (p1[1] + 3 * c1[1] + 3 * c2[1] + p2[1]) / 8];
  return { d: `M${p1[0]},${p1[1]} C${c1[0]},${c1[1]} ${c2[0]},${c2[1]} ${p2[0]},${p2[1]}`, mid };
}
let edgeRaf = 0;
function requestEdges() { if (!edgeRaf) edgeRaf = requestAnimationFrame(() => { edgeRaf = 0; renderEdges(); }); }
function renderEdges() {
  edgeLayer.innerHTML = '';
  for (const e of S.edges.values()) {
    if (!S.nodes.has(e.source_id) || !S.nodes.has(e.target_id)) continue;
    const g = geometry(box(e.source_id), box(e.target_id));
    const isV = S.nodes.get(e.source_id).type === 'validator' || S.nodes.get(e.target_id).type === 'validator';
    const selected = S.sel && S.sel.kind === 'edge' && S.sel.id === e.id;
    const grp = svg('g', { class: 'edge' + (isV ? ' validator' : '') + (selected ? ' selected' : ''), 'data-id': e.id });
    grp.append(svg('path', { class: 'line', d: g.d, 'marker-end': `url(#${selected ? 'arrowSel' : isV ? 'arrowV' : 'arrow'})` }));
    const hit = svg('path', { class: 'hit', d: g.d }); grp.append(hit);
    if (e.label) { const t = svg('text', { x: g.mid[0], y: g.mid[1] + 4, 'text-anchor': 'middle' }); t.textContent = e.label; grp.append(t); }
    grp.addEventListener('pointerdown', ev => { ev.stopPropagation(); select({ kind: 'edge', id: e.id }); });
    grp.addEventListener('dblclick', ev => { ev.stopPropagation(); editEdgeLabel(e.id); });
    edgeLayer.append(grp);
  }
}
async function editEdgeLabel(id) {
  const e = S.edges.get(id); if (!e) return;
  const v = await formModal('Edge label', [{ key: 'label', label: 'Label (optional, e.g. "lookup", "validates", "variance")', value: e.label }], 'Save');
  if (v) setEdgeLabel(id, v.label);
}
async function setEdgeLabel(id, label) {
  const e = S.edges.get(id); if (!e) return;
  e.label = label; renderEdges();
  try { await api('PATCH', '/api/edges/' + id, { label }); } catch (er) { fail(er); }
}
async function createEdge(source_id, target_id) {
  if (source_id === target_id) return;
  for (const e of S.edges.values()) if (e.source_id === source_id && e.target_id === target_id) { toast('Already connected'); return; }
  try {
    const e = await api('POST', `/api/projects/${S.project.id}/edges`, { source_id, target_id, label: '' });
    S.edges.set(e.id, e); renderEdges(); select({ kind: 'edge', id: e.id });
  } catch (er) { fail(er); }
}
async function deleteEdge(id) {
  S.edges.delete(id); if (S.sel && S.sel.id === id) S.sel = null; renderEdges(); renderPanel();
  try { await api('DELETE', '/api/edges/' + id); } catch (er) { fail(er); }
}

/* ---------------- Node CRUD ---------------- */
async function addNode(type, at) {
  if (!S.project) return;
  const r = canvas.getBoundingClientRect();
  let p = at || toWorld(r.left + r.width / 2 - 110 * S.view.k, r.top + r.height / 2 - 40 * S.view.k);
  // avoid stacking exactly on top of an existing node
  for (let i = 0; i < 20; i++) { let clash = false; for (const n of S.nodes.values()) if (Math.abs(n.x - p.x) < 30 && Math.abs(n.y - p.y) < 30) clash = true; if (!clash) break; p = { x: p.x + 36, y: p.y + 36 }; }
  try {
    const n = await api('POST', `/api/projects/${S.project.id}/nodes`, { type, title: '', x: Math.round(p.x), y: Math.round(p.y), data: {} });
    S.nodes.set(n.id, n); buildNode(n); updateEmpty();
    select({ kind: 'node', id: n.id });
    const t = $('.title', S.els.get(n.id)); t.focus();
  } catch (e) { fail(e); }
}
async function deleteNode(id) {
  const n = S.nodes.get(id); if (!n) return;
  clearTimeout(S.timers.get(id)); S.timers.delete(id);
  S.nodes.delete(id); const el = S.els.get(id); if (el) el.remove(); S.els.delete(id);
  for (const e of Array.from(S.edges.values())) if (e.source_id === id || e.target_id === id) S.edges.delete(e.id);
  S.sel = null; renderEdges(); renderPanel(); updateEmpty();
  try { await api('DELETE', '/api/nodes/' + id); toast('Deleted ' + (n.title || T(n.type).label)); } catch (e) { fail(e); }
}
async function duplicateNode(id) {
  const n = S.nodes.get(id); if (!n) return;
  try {
    const c = await api('POST', `/api/projects/${S.project.id}/nodes`, { type: n.type, title: n.title ? n.title + ' (copy)' : '', x: n.x + 40, y: n.y + 40, data: n.data });
    S.nodes.set(c.id, c); buildNode(c); select({ kind: 'node', id: c.id });
  } catch (e) { fail(e); }
}

/* ---------------- Selection & panel ---------------- */
function select(sel, keepFocus) {
  const prev = S.sel; S.sel = sel;
  if (prev && prev.kind === 'node') refreshNodeSel(prev.id);
  if (sel && sel.kind === 'node') refreshNodeSel(sel.id);
  if ((prev && prev.kind === 'edge') || (sel && sel.kind === 'edge')) renderEdges();
  if (!prev || !sel || prev.kind !== sel.kind || prev.id !== sel.id) renderPanel();
}
function refreshNodeSel(id) { const el = S.els.get(id); if (el) el.classList.toggle('selected', !!(S.sel && S.sel.kind === 'node' && S.sel.id === id)); }

function panelField(label, inp) { return h('div', { class: 'field' }, h('label', { text: label }), inp); }
function renderPanel() {
  const P = $('#panel'); P.innerHTML = '';
  if (!S.project) { P.append(h('p', { class: 'muted', text: 'No project selected.' })); return; }
  if (S.sel && S.sel.kind === 'node' && S.nodes.has(S.sel.id)) return renderNodePanel(P, S.nodes.get(S.sel.id));
  if (S.sel && S.sel.kind === 'edge' && S.edges.has(S.sel.id)) return renderEdgePanel(P, S.edges.get(S.sel.id));
  renderProjectPanel(P);
}
function renderNodePanel(P, n) {
  const t = T(n.type);
  P.append(h('span', { class: 'typebar', text: t.label, style: `background:${t.color}` }));
  const ti = h('input', { type: 'text', placeholder: t.title_placeholder, 'data-key': '__title' }); ti.value = n.title || '';
  ti.addEventListener('input', () => { n.title = ti.value; const el = S.els.get(n.id); $('.title', el).textContent = n.title; scheduleNodeSave(n.id); requestEdges(); });
  P.append(panelField(t.title_label, ti));
  for (const f of t.fields) P.append(panelField(f.label, fieldInput(n, f, false)));
  // connections
  const ins = [], outs = [];
  for (const e of S.edges.values()) { if (e.target_id === n.id) ins.push(e); if (e.source_id === n.id) outs.push(e); }
  const list = (arr, other) => {
    const ul = h('ul', { class: 'conn-list' });
    if (!arr.length) ul.append(h('li', { class: 'muted', text: 'None – drag the ● handle to connect' }));
    for (const e of arr) {
      const o = S.nodes.get(e[other]); if (!o) continue;
      ul.append(h('li', {}, h('span', { class: `pill t-${o.type}`, text: T(o.type).label }),
        h('a', { text: o.title || '(untitled)', onclick: () => { select({ kind: 'node', id: o.id }); centerOn(o.id); } }),
        e.label ? h('span', { class: 'muted', text: '“' + e.label + '”' }) : null,
        h('button', { class: 'x', title: 'Remove connection', text: '✕', onclick: () => deleteEdge(e.id) })));
    }
    return ul;
  };
  P.append(h('div', { class: 'section-title', text: 'Comes from' }), list(ins, 'source_id'));
  P.append(h('div', { class: 'section-title', text: 'Goes to' }), list(outs, 'target_id'));
  P.append(h('div', { class: 'row' },
    h('button', { text: 'Duplicate node', onclick: () => duplicateNode(n.id) }),
    h('button', { class: 'danger', text: 'Delete node', onclick: () => deleteNode(n.id) })));
  P.append(h('div', { class: 'hint', html: 'Saved automatically. Tip: type directly on the node, or click <b>▸</b> on the node to edit fields in place. <kbd>Del</kbd> deletes the selected item, <kbd>Esc</kbd> deselects.' }));
}
function renderEdgePanel(P, e) {
  const s = S.nodes.get(e.source_id), t = S.nodes.get(e.target_id);
  P.append(h('h3', { text: 'Connection' }));
  P.append(h('div', { class: 'sub' }, (s && s.title) || '(untitled)', '  →  ', (t && t.title) || '(untitled)'));
  const li = h('input', { type: 'text', placeholder: 'e.g. lookup, GL balances, validates, signs off' }); li.value = e.label || '';
  let timer; li.addEventListener('input', () => { e.label = li.value; renderEdges(); clearTimeout(timer); timer = setTimeout(() => setEdgeLabel(e.id, li.value), 400); });
  P.append(panelField('Label (optional)', li));
  P.append(h('div', { class: 'row' },
    h('button', { text: 'Select source', onclick: () => select({ kind: 'node', id: e.source_id }) }),
    h('button', { text: 'Select target', onclick: () => select({ kind: 'node', id: e.target_id }) }),
    h('button', { class: 'danger', text: 'Delete connection', onclick: () => deleteEdge(e.id) })));
  setTimeout(() => li.focus(), 0);
}
function renderProjectPanel(P) {
  const p = S.project;
  P.append(h('h3', { text: p.name }), h('div', { class: 'sub', text: (p.client || 'No client') + ' · project #' + p.id + ' · updated ' + (p.updated_at || '').slice(0, 16).replace('T', ' ') }));
  const counts = { input: 0, process: 0, output: 0, validator: 0 };
  for (const n of S.nodes.values()) counts[n.type]++;
  P.append(h('div', { class: 'stats' }, ...Object.keys(counts).map(k => h('div', { class: 'stat t-' + k }, h('b', { text: counts[k] }), T(k).label.split(' ')[0]))));
  P.append(h('div', { class: 'hint', html: '<b>How to use:</b> add nodes from the toolbar, type on them, drag the <b>●</b> handle onto another node to connect. Click a node or line to edit its details here. Pan by dragging the background, zoom with the mouse wheel. Everything autosaves.' }));
  P.append(h('div', { class: 'section-title', text: 'Project snapshot' }));
  let timer; const pending = {};
  const save = () => { if (!timer) { S.inflight++; setStatus(); } clearTimeout(timer); timer = setTimeout(async () => { timer = null; S.inflight--; const body = Object.assign({}, pending); for (const k in pending) delete pending[k]; try { const r = await api('PATCH', '/api/projects/' + p.id, body); Object.assign(S.project, r); if (body.name !== undefined || body.client !== undefined) loadProjects(); } catch (e) { fail(e); } }, 500); };
  const top = (key, label, ph) => { const i = h('input', { type: 'text', placeholder: ph || '' }); i.value = p[key] || ''; if (key === 'client') i.setAttribute('list', 'clientList'); i.addEventListener('input', () => { if (key === 'name' && !i.value.trim()) return; p[key] = i.value; pending[key] = i.value; save(); }); return panelField(label, i); };
  P.append(clientDatalist());
  P.append(top('client', 'Client', 'e.g. Example Client A'), top('name', 'Project name', 'e.g. Month-End Claims Reconciliation Automation'));
  const di = h('textarea', { placeholder: 'Short description' }); di.value = p.description || ''; di.addEventListener('input', () => { p.description = di.value; pending.description = di.value; save(); });
  P.append(panelField('Description', di));
  for (const f of S.schema.project_meta_fields) {
    const inp = f.kind === 'textarea' ? h('textarea', { placeholder: f.placeholder || '' }) : h('input', { type: f.kind === 'date' ? 'date' : 'text', placeholder: f.placeholder || '' });
    inp.value = (p.meta || {})[f.key] || '';
    inp.addEventListener('input', () => { p.meta = p.meta || {}; p.meta[f.key] = inp.value; pending.meta = Object.assign(pending.meta || {}, { [f.key]: inp.value }); save(); });
    P.append(panelField(f.label, inp));
  }
  P.append(h('div', { class: 'row' }, h('button', { class: 'primary', text: 'Start new project from this one…', onclick: () => newProjectDialog(p.id) })));
}
function clientDatalist() {
  const dl = h('datalist', { id: 'clientList' });
  const names = new Set(S.schema.known_clients); S.projects.forEach(p => p.client && names.add(p.client));
  for (const c of names) dl.append(h('option', { value: c }));
  const old = $('#clientList'); if (old) old.remove();
  return dl;
}

/* ---------------- Pointer interactions ---------------- */
let drag = null;
function isEditable(t) { return t.closest('input,textarea,select,button,[contenteditable="true"]'); }
function onNodePointerDown(e) {
  if (e.button !== 0) return;
  const el = e.currentTarget, id = el.dataset.id;
  if (e.target.classList.contains('handle')) return;
  if (isEditable(e.target)) { if (!(S.sel && S.sel.id === id)) select({ kind: 'node', id }, true); return; }
  e.preventDefault(); e.stopPropagation();
  if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  select({ kind: 'node', id });
  const n = S.nodes.get(id), w = toWorld(e.clientX, e.clientY);
  drag = { kind: 'node', id, dx: w.x - n.x, dy: w.y - n.y, moved: false };
  canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId);
}
function onHandlePointerDown(e) {
  if (e.button !== 0) return;
  e.preventDefault(); e.stopPropagation();
  const id = e.currentTarget.parentElement.dataset.id;
  drag = { kind: 'connect', id };
  canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId);
}
canvas.addEventListener('pointerdown', e => {
  if (e.button !== 0 && e.button !== 1) return;
  if (e.target.closest('.node') || e.target.closest('#legend')) return;
  if (document.activeElement && document.activeElement !== canvas && document.activeElement.blur) document.activeElement.blur();
  if (S.sel) select(null);
  drag = { kind: 'pan', sx: e.clientX, sy: e.clientY, vx: S.view.x, vy: S.view.y };
  canvas.classList.add('panning'); canvas.focus({ preventScroll: true });
  canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener('pointermove', e => {
  if (!drag) return;
  if (drag.kind === 'pan') { S.view.x = drag.vx + e.clientX - drag.sx; S.view.y = drag.vy + e.clientY - drag.sy; applyView(); }
  else if (drag.kind === 'node') {
    const n = S.nodes.get(drag.id), w = toWorld(e.clientX, e.clientY);
    n.x = Math.round(w.x - drag.dx); n.y = Math.round(w.y - drag.dy); drag.moved = true;
    const el = S.els.get(drag.id); el.style.left = n.x + 'px'; el.style.top = n.y + 'px'; requestEdges();
  } else if (drag.kind === 'connect') {
    const b = box(drag.id), p1 = anchor(b, 'r'), w = toWorld(e.clientX, e.clientY);
    tempEdge.setAttribute('d', `M${p1[0]},${p1[1]} C${p1[0] + 60},${p1[1]} ${w.x - 60},${w.y} ${w.x},${w.y}`);
    $$('.node.connect-target').forEach(x => x.classList.remove('connect-target'));
    const over = document.elementFromPoint(e.clientX, e.clientY); const tn = over && over.closest('.node');
    if (tn && tn.dataset.id !== drag.id) tn.classList.add('connect-target');
  }
});
function endDrag(e) {
  if (!drag) return;
  const d = drag; drag = null; canvas.classList.remove('panning');
  if (d.kind === 'node' && d.moved) scheduleNodeSave(d.id, 50);
  if (d.kind === 'connect') {
    tempEdge.setAttribute('d', ''); $$('.node.connect-target').forEach(x => x.classList.remove('connect-target'));
    const over = e && document.elementFromPoint(e.clientX, e.clientY); const tn = over && over.closest('.node');
    if (tn && tn.dataset.id !== d.id) createEdge(d.id, tn.dataset.id);
  }
}
canvas.addEventListener('pointerup', endDrag);
canvas.addEventListener('pointercancel', () => endDrag(null));
canvas.addEventListener('wheel', e => {
  e.preventDefault();
  if (e.ctrlKey || e.metaKey || Math.abs(e.deltaY) >= Math.abs(e.deltaX)) zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX, e.clientY);
  else { S.view.x -= e.deltaX; applyView(); }
}, { passive: false });
canvas.addEventListener('dblclick', e => {
  if (e.target.closest('.node') || e.target.closest('.edge')) return;
  const w = toWorld(e.clientX, e.clientY);
  quickAddMenu(e.clientX, e.clientY, { x: Math.round(w.x - 110), y: Math.round(w.y - 30) });
});
function quickAddMenu(cx, cy, at) {
  const m = h('div', { class: 'menu-items open', style: `left:${cx}px;top:${cy}px` });
  for (const t of Object.keys(S.schema.node_types)) m.append(h('button', { text: '＋ ' + T(t).label, onclick: () => { m.remove(); addNode(t, at); } }));
  document.body.append(m);
  setTimeout(() => document.addEventListener('pointerdown', function off(ev) { if (!m.contains(ev.target)) { m.remove(); document.removeEventListener('pointerdown', off); } }), 0);
}
document.addEventListener('keydown', e => {
  if (!$('#modalBackdrop').hidden) { if (e.key === 'Escape') closeModal(null); return; }
  if (isEditable(e.target)) return;
  if ((e.key === 'Delete' || e.key === 'Backspace') && S.sel) {
    e.preventDefault();
    if (S.sel.kind === 'node') deleteNode(S.sel.id); else deleteEdge(S.sel.id);
  } else if (e.key === 'Escape') select(null);
  else if (e.key === 'Enter' && S.sel && S.sel.kind === 'node') { e.preventDefault(); const t = $('.title', S.els.get(S.sel.id)); t.focus(); placeCaretEnd(t); }
});

/* ---------------- Tidy layout ---------------- */
async function tidy() {
  const nodes = Array.from(S.nodes.values()); if (!nodes.length) return;
  const flow = nodes.filter(n => n.type !== 'validator');
  const depth = new Map(flow.map(n => [n.id, n.type === 'input' ? 0 : 1]));
  const flowEdges = Array.from(S.edges.values()).filter(e => depth.has(e.source_id) && depth.has(e.target_id));
  for (let i = 0; i < flow.length + 1; i++) {   // longest path (bounded for cycles)
    let changed = false;
    for (const e of flowEdges) { const d = depth.get(e.source_id) + 1; if (d > depth.get(e.target_id) && d < flow.length + 2) { depth.set(e.target_id, d); changed = true; } }
    if (!changed) break;
  }
  for (const n of flow) if (n.type === 'input') {   // pull inputs next to the step they feed
    const ts = flowEdges.filter(e => e.source_id === n.id).map(e => depth.get(e.target_id));
    if (ts.length) depth.set(n.id, Math.max(0, Math.min(...ts) - 1));
  }
  const maxD = Math.max(0, ...depth.values());
  for (const n of flow) if (n.type === 'output' && !flowEdges.some(e => e.source_id === n.id)) depth.set(n.id, Math.max(depth.get(n.id), maxD));
  const cols = new Map();
  for (const n of flow) { const d = depth.get(n.id); if (!cols.has(d)) cols.set(d, []); cols.get(d).push(n); }
  const X = 300, GAP = 60; let maxY = 0;
  for (const [d, list] of cols) { list.sort((a, b) => a.y - b.y); let y = 40; list.forEach(n => { n.x = 40 + d * X; n.y = y; y += box(n.id).h + GAP; maxY = Math.max(maxY, y); }); }
  const vals = nodes.filter(n => n.type === 'validator');
  vals.forEach(v => { const e = Array.from(S.edges.values()).find(e => e.source_id === v.id || e.target_id === v.id); const o = e && S.nodes.get(e.source_id === v.id ? e.target_id : e.source_id); v._tx = o && o.type !== 'validator' ? o.x : 99999; });
  vals.sort((a, b) => a._tx - b._tx);
  let lastX = -Infinity;
  vals.forEach(v => { let x = v._tx === 99999 ? lastX + 260 : v._tx; if (x < lastX + 250) x = lastX + 250; if (!isFinite(x)) x = 40; v.x = x; v.y = maxY + 80; lastX = x; delete v._tx; });
  for (const n of nodes) refreshNode(n.id);
  renderEdges(); fitView();
  try { await api('PUT', `/api/projects/${S.project.id}/layout`, { positions: nodes.map(n => ({ id: n.id, x: n.x, y: n.y })) }); } catch (e) { fail(e); }
}

/* ---------------- Modals ---------------- */
let modalResolve = null;
function openModal(title, body, buttons, wide) {
  const m = $('#modal'); m.innerHTML = ''; m.className = wide ? 'wide' : '';
  m.append(h('div', { class: 'm-head' }, title, h('button', { class: 'close', text: '✕', onclick: () => closeModal(null) })));
  m.append(h('div', { class: 'm-body' }, body));
  if (buttons && buttons.length) m.append(h('div', { class: 'm-foot' }, buttons));
  $('#modalBackdrop').hidden = false;
  return new Promise(res => { modalResolve = res; });
}
function closeModal(v) { $('#modalBackdrop').hidden = true; $('#modal').innerHTML = ''; const r = modalResolve; modalResolve = null; if (r) r(v); }
$('#modalBackdrop').addEventListener('pointerdown', e => { if (e.target.id === 'modalBackdrop') closeModal(null); });
function formModal(title, fields, okText) {
  const form = h('form', { onsubmit: ev => { ev.preventDefault(); ok(); } });
  const inputs = {};
  for (const f of fields) {
    let inp;
    if (f.type === 'select') { inp = h('select'); for (const o of f.options) inp.append(o.group ? (() => { const g = h('optgroup', { label: o.group }); o.options.forEach(x => g.append(h('option', { value: x.value, text: x.label }))); return g; })() : h('option', { value: o.value, text: o.label })); }
    else if (f.type === 'radio') { inp = h('div', { class: 'radio-row' }); f.options.forEach((o, i) => inp.append(h('label', {}, h('input', { type: 'radio', name: f.key, value: o.value, checked: (f.value ? f.value === o.value : i === 0) }), o.label))); }
    else if (f.type === 'textarea') inp = h('textarea', { placeholder: f.placeholder || '' });
    else inp = h('input', { type: 'text', placeholder: f.placeholder || '', list: f.list || null });
    if (f.value != null && f.type !== 'radio') inp.value = f.value;
    inputs[f.key] = inp;
    const wrap = panelField(f.label, inp); if (f.id) wrap.id = f.id; form.append(wrap);
  }
  if (fields.some(f => f.list === 'clientListM')) { const dl = clientDatalist(); dl.id = 'clientListM'; form.append(dl); }
  form.append(h('button', { type: 'submit', hidden: true }));
  const values = () => { const v = {}; for (const f of fields) v[f.key] = f.type === 'radio' ? ((form.querySelector(`input[name="${f.key}"]:checked`) || {}).value) : inputs[f.key].value; return v; };
  const ok = () => closeModal(values());
  const p = openModal(title, form, [h('button', { text: 'Cancel', onclick: () => closeModal(null) }), h('button', { class: 'primary', text: okText || 'OK', onclick: ok })]);
  formModal.onRender && formModal.onRender(form, inputs);
  setTimeout(() => { const first = form.querySelector('input,textarea,select'); if (first) first.focus(); }, 0);
  return p;
}

/* ---------------- Project dialogs ---------------- */
async function newProjectDialog(preselectId) {
  const opts = [{ value: 'blank', label: 'Blank canvas' }, { value: 'skeleton', label: 'DSL starter skeleton (inputs → process → output, walkthrough & sign-off people)' }];
  const byClient = {};
  for (const p of S.projects) (byClient[p.client || '(no client)'] = byClient[p.client || '(no client)'] || []).push({ value: 'project:' + p.id, label: p.name });
  for (const [c, list] of Object.entries(byClient)) opts.push({ group: 'Seed from an existing project — ' + c, options: list });
  formModal.onRender = (form, inputs) => {
    const sync = () => { const wrap = form.querySelector('#copyModeWrap'); wrap.style.display = inputs.start.value.startsWith('project:') ? '' : 'none'; };
    inputs.start.addEventListener('change', sync); if (preselectId) inputs.start.value = 'project:' + preselectId; sync();
  };
  const v = await formModal('New project', [
    { key: 'client', label: 'Client', placeholder: 'e.g. Example Client A, Example Client B', list: 'clientListM', value: preselectId ? (S.projects.find(p => p.id == preselectId) || {}).client : '' },
    { key: 'name', label: 'Project name', placeholder: 'e.g. Month-End Claims Reconciliation Automation' },
    { key: 'description', label: 'Description (optional)', type: 'textarea' },
    { key: 'start', label: 'Start from', type: 'select', options: opts },
    { key: 'copy_mode', id: 'copyModeWrap', label: 'What to copy from the earlier project', type: 'radio', options: [
      { value: 'structure', label: 'Structure only – node types, titles, systems & roles (blank details, people names cleared)' },
      { value: 'full', label: 'Everything – all fields, people and contact details' }] },
  ], 'Create project');
  formModal.onRender = null;
  if (!v) return;
  if (!v.name.trim()) { toast('Project name is required', true); return newProjectDialog(preselectId); }
  const body = { client: v.client.trim(), name: v.name.trim(), description: v.description };
  if (v.start.startsWith('project:')) Object.assign(body, { start_from: 'project', source_project_id: +v.start.split(':')[1], copy_mode: v.copy_mode || 'structure' });
  else body.start_from = v.start;
  try { const p = await api('POST', '/api/projects', body); await loadProjects(); await openProject(p.id); toast('Project created'); } catch (e) { fail(e); }
}
async function renameDialog() {
  const p = S.project; if (!p) return;
  const v = await formModal('Rename project', [{ key: 'client', label: 'Client', value: p.client, list: 'clientListM' }, { key: 'name', label: 'Project name', value: p.name }], 'Save');
  if (!v) return; if (!v.name.trim()) return toast('Project name cannot be empty', true);
  try { const r = await api('PATCH', '/api/projects/' + p.id, { client: v.client.trim(), name: v.name.trim() }); Object.assign(S.project, r); await loadProjects(); renderPanel(); document.title = r.name + ' · Flow KB'; } catch (e) { fail(e); }
}
async function duplicateDialog() {
  const p = S.project; if (!p) return;
  const v = await formModal('Duplicate project', [{ key: 'client', label: 'Client', value: p.client, list: 'clientListM' }, { key: 'name', label: 'New project name', value: 'Copy of ' + p.name },
    { key: 'copy_mode', label: 'Copy', type: 'radio', options: [{ value: 'full', label: 'Everything' }, { value: 'structure', label: 'Structure only (blank details)' }] }], 'Duplicate');
  if (!v) return;
  flushAll();
  try { const r = await api('POST', `/api/projects/${p.id}/duplicate`, { client: v.client.trim(), name: v.name.trim(), copy_mode: v.copy_mode }); await loadProjects(); await openProject(r.id); toast('Duplicated'); } catch (e) { fail(e); }
}
async function deleteProjectDialog() {
  const p = S.project; if (!p) return;
  const v = await openModal('Delete project?', h('p', {}, 'Permanently delete ', h('b', { text: projectLabel(p) }), ` and its ${S.nodes.size} nodes? Export it as JSON first if you might need it again.`),
    [h('button', { text: 'Cancel', onclick: () => closeModal(null) }), h('button', { class: 'danger', text: 'Delete project', onclick: () => closeModal(true) })]);
  if (!v) return;
  try {
    await api('DELETE', '/api/projects/' + p.id); localStorage.removeItem('flowkb.view.' + p.id); S.project = null; await loadProjects();
    if (S.projects.length) await openProject(S.projects[0].id); else { S.nodes.clear(); S.edges.clear(); renderAll(); renderPanel(); }
    toast('Project deleted');
  } catch (e) { fail(e); }
}

/* ---------------- Export / import ---------------- */
async function doExport(kind) {
  if (kind === 'all') { location.href = '/api/export-all?download=1'; return; }
  if (!S.project) return;
  flushAll();
  await new Promise(r => setTimeout(r, 150));
  const url = `/api/projects/${S.project.id}/export?format=${kind}`;
  try {
    const text = await api('GET', url);
    const body = typeof text === 'string' ? text : JSON.stringify(text, null, 2);
    const titles = { markdown: 'Markdown report', mermaid: 'Mermaid flowchart', json: 'Project JSON' };
    const pre = h('pre', { text: body });
    const extra = kind === 'mermaid' ? h('p', { class: 'muted', html: 'Paste into <b>mermaid.live</b>, GitHub, Azure DevOps, Notion, Obsidian or VS Code to render.' }) :
      kind === 'markdown' ? h('p', { class: 'muted', text: 'Follows the DSL starter template sections 0–6 plus the quick-start checklist, generated from the canvas.' }) : null;
    openModal(titles[kind], h('div', {}, extra, pre), [
      h('button', { text: 'Copy to clipboard', onclick: async () => { try { await navigator.clipboard.writeText(body); toast('Copied'); } catch (e) { const r = document.createRange(); r.selectNodeContents(pre); getSelection().removeAllRanges(); getSelection().addRange(r); document.execCommand('copy'); toast('Copied'); } } }),
      h('a', { href: url + '&download=1' }, h('button', { class: 'primary', text: 'Download file' }))], true);
  } catch (e) { fail(e); }
}
async function doImport(file) {
  try {
    const doc = JSON.parse(await file.text());
    const r = await api('POST', '/api/import', doc);
    await loadProjects();
    if (r.imported_project_ids && r.imported_project_ids.length) await openProject(r.imported_project_ids[r.imported_project_ids.length - 1]);
    toast(`Imported ${r.imported_project_ids.length} project(s)`);
  } catch (e) { fail(e.message.includes('JSON') ? new Error('That file is not valid Flow KB JSON') : e); }
}

/* ---------------- Cross-project search ---------------- */
const PRESETS = [
  { label: 'All validators & contacts', type: 'validator', group: 'responsibility' },
  { label: 'Sign-off owners', type: 'validator', field: 'responsibility', value: 'Sign-off owner', group: 'client' },
  { label: 'Input sources by source system', type: 'input', group: 'source_system' },
  { label: 'Manual process steps', type: 'process', field: 'manual', value: 'Y', group: 'client' },
  { label: 'Process steps by tool', type: 'process', group: 'tool' },
  { label: 'Artifacts / outputs', type: 'output', group: 'client' },
];
function searchDialog() {
  const typeSel = h('select'); typeSel.append(h('option', { value: '', text: 'All node types' }));
  for (const t of Object.keys(S.schema.node_types)) typeSel.append(h('option', { value: t, text: T(t).label }));
  const clientSel = h('select'); clientSel.append(h('option', { value: '', text: 'All clients' }));
  const clients = new Set(S.projects.map(p => p.client).filter(Boolean)); clients.forEach(c => clientSel.append(h('option', { value: c, text: c })));
  const q = h('input', { type: 'search', placeholder: 'Search text (titles & all fields), e.g. SAP, claims, reconcil…' });
  const groupSel = h('select', { title: 'Group results by' });
  [['', 'No grouping'], ['client', 'Group by client'], ['project_name', 'Group by project'], ['type', 'Group by type'], ['source_system', 'Group by source system'], ['owner', 'Group by owner'], ['tool', 'Group by tool'], ['responsibility', 'Group by responsibility'], ['organisation', 'Group by organisation']].forEach(([v, l]) => groupSel.append(h('option', { value: v, text: l })));
  const out = h('div', { class: 'muted', text: 'Pick a preset or search…' });
  let field = '', value = '';
  const run = async () => {
    const params = new URLSearchParams({ type: typeSel.value, q: q.value, client: clientSel.value, field, value });
    try { renderResults(out, await api('GET', '/api/search?' + params), groupSel.value, typeSel.value); } catch (e) { fail(e); }
  };
  const presets = h('div', { class: 'presets' }, PRESETS.map(p => h('button', { text: p.label, onclick: () => { typeSel.value = p.type; field = p.field || ''; value = p.value || ''; groupSel.value = p.group || ''; q.value = ''; run(); } })));
  let t; q.addEventListener('input', () => { field = ''; value = ''; clearTimeout(t); t = setTimeout(run, 250); });
  [typeSel, clientSel, groupSel].forEach(s => s.addEventListener('change', () => { if (s !== groupSel) { field = ''; value = ''; } run(); }));
  openModal('Search the knowledge base (all projects)', h('div', {}, presets, h('div', { class: 'searchbar' }, q, typeSel, clientSel, groupSel), out), [], true);
  setTimeout(() => q.focus(), 0);
}
function resultCols(type) {
  if (type === 'validator') return [['role', 'Role'], ['organisation', 'Organisation'], ['responsibility', 'Responsibility'], ['email', 'Email'], ['phone', 'Phone']];
  if (type === 'input') return [['source_system', 'Source system'], ['owner', 'Owner'], ['format', 'Format'], ['refresh', 'Refresh']];
  if (type === 'process') return [['performed_by', 'Performed by'], ['tool', 'Tool'], ['time_taken', 'Time'], ['manual', 'Manual?']];
  if (type === 'output') return [['location', 'Location'], ['frequency', 'Frequency'], ['consumers', 'Consumers'], ['effort', 'Effort']];
  return [['__summary', 'Details']];
}
function renderResults(out, rows, group, type) {
  out.innerHTML = '';
  out.className = '';
  if (!rows.length) { out.append(h('p', { class: 'muted', text: 'No matches.' })); return; }
  const cols = resultCols(type);
  const tbl = h('table', { class: 'results' });
  tbl.append(h('thead', {}, h('tr', {}, h('th', { text: 'Type' }), h('th', { text: 'Title' }), cols.map(c => h('th', { text: c[1] })), h('th', { text: 'Client' }), h('th', { text: 'Project' }))));
  const tb = h('tbody'); tbl.append(tb);
  const gv = r => group === 'client' ? r.client : group === 'project_name' ? r.project_name : group === 'type' ? T(r.type).label : (r.data || {})[group];
  let list = rows.slice();
  if (group) list.sort((a, b) => String(gv(a) || '~').localeCompare(String(gv(b) || '~')));
  let last = null;
  for (const r of list) {
    if (group) { const g = gv(r) || '(not set)'; if (g !== last) { const n = list.filter(x => (gv(x) || '(not set)') === g).length; tb.append(h('tr', { class: 'group-head' }, h('td', { colspan: cols.length + 4, text: `${g}  (${n})` }))); last = g; } }
    tb.append(h('tr', { class: 'clickable', title: 'Open in its project', onclick: async () => { closeModal(null); await openProject(r.project_id, r.id); } },
      h('td', {}, h('span', { class: 'pill t-' + r.type, text: T(r.type).label })), h('td', { text: r.title || '(untitled)' }),
      cols.map(c => h('td', { html: c[0] === '__summary' ? summaryText(r) : esc((r.data || {})[c[0]] || '') })),
      h('td', { text: r.client || '' }), h('td', { text: r.project_name })));
  }
  out.append(h('p', { class: 'muted', text: `${rows.length} result(s). Click a row to open it.` }), tbl);
}

/* ---------------- SQL console ---------------- */
const SQL_PRESETS = [
  ['Validators across all clients', "SELECT client, project, name, role, responsibility, email, phone\nFROM v_validators ORDER BY client, responsibility, name;"],
  ['Inputs by source system', "SELECT source_system, COUNT(*) AS uses, GROUP_CONCAT(DISTINCT client) AS clients\nFROM v_inputs GROUP BY source_system ORDER BY uses DESC;"],
  ['Manual effort by project', "SELECT client, project, COUNT(*) AS steps,\n       SUM(manual = 'Y') AS manual_steps,\n       GROUP_CONCAT(json_extract(data, '$.time_taken'), '; ') AS time_taken\nFROM v_processes GROUP BY project_id ORDER BY manual_steps DESC;"],
  ['Lineage (all edges)', "SELECT client, project, source_type, source, label, target_type, target\nFROM v_edges ORDER BY client, project;"],
  ['Projects & node counts', "SELECT p.id, p.client, p.name, n.type, COUNT(n.id) AS nodes\nFROM projects p LEFT JOIN nodes n ON n.project_id = p.id\nGROUP BY p.id, n.type ORDER BY p.client, p.name;"],
];
function sqlDialog() {
  const ta = h('textarea', { class: 'code', spellcheck: 'false' }); ta.value = SQL_PRESETS[0][1];
  const out = h('div', { class: 'muted', text: 'Read-only. Tables: projects, nodes, edges. Views: v_nodes, v_inputs, v_processes, v_outputs, v_validators, v_edges.' });
  let last = null;
  const run = async () => {
    try {
      const r = await api('POST', '/api/sql', { sql: ta.value }); last = r; out.innerHTML = ''; out.className = '';
      const tbl = h('table', { class: 'results' }, h('thead', {}, h('tr', {}, r.columns.map(c => h('th', { text: c })))),
        h('tbody', {}, r.rows.map(row => h('tr', {}, row.map(v => h('td', { text: v == null ? '' : String(v).length > 300 ? String(v).slice(0, 300) + '…' : v }))))));
      out.append(h('p', { class: 'muted', text: `${r.rows.length} row(s)${r.truncated ? ' (truncated at 5000)' : ''}` }), tbl);
    } catch (e) { out.innerHTML = ''; out.className = ''; out.append(h('p', { style: 'color:#dc2626', text: e.message })); }
  };
  const csv = () => {
    if (!last) return toast('Run a query first', true);
    const q = v => { const s = v == null ? '' : String(v); return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const text = [last.columns.map(q).join(',')].concat(last.rows.map(r => r.map(q).join(','))).join('\r\n');
    const a = h('a', { href: URL.createObjectURL(new Blob(['\ufeff' + text], { type: 'text/csv' })), download: 'flowkb_query.csv' }); document.body.append(a); a.click(); a.remove();
  };
  ta.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); } });
  openModal('SQL query (read-only)', h('div', {},
    h('div', { class: 'presets' }, SQL_PRESETS.map(([l, s]) => h('button', { text: l, onclick: () => { ta.value = s; run(); } }))),
    ta, h('div', { class: 'row', style: 'margin:8px 0' }, h('button', { class: 'primary', text: 'Run (Ctrl+Enter)', onclick: run }), h('button', { text: 'Download CSV', onclick: csv })), out),
  [], true);
}

/* ---------------- Toolbar wiring ---------------- */
function wire() {
  $('#projectSelect').addEventListener('change', e => openProject(e.target.value).catch(fail));
  $('#btnNew').addEventListener('click', () => newProjectDialog());
  $('#btnRename').addEventListener('click', renameDialog);
  $('#btnDuplicate').addEventListener('click', duplicateDialog);
  $('#btnDeleteProject').addEventListener('click', deleteProjectDialog);
  $$('.add-node').forEach(b => b.addEventListener('click', () => addNode(b.dataset.type)));
  $('#btnTidy').addEventListener('click', tidy);
  $('#btnFit').addEventListener('click', fitView);
  $('#btnZoomIn').addEventListener('click', () => zoomAt(1.2));
  $('#btnZoomOut').addEventListener('click', () => zoomAt(1 / 1.2));
  const menus = [['#btnExport', '#exportMenu'], ['#btnProjectMenu', '#projectMenu']];
  for (const [b, m] of menus) $(b).addEventListener('click', e => {
    e.stopPropagation(); const menu = $(m), open = menu.classList.contains('open');
    $$('.menu-items.open').forEach(x => x.classList.remove('open'));
    if (!open) { const r = e.currentTarget.getBoundingClientRect(); menu.style.left = Math.min(r.left, innerWidth - 280) + 'px'; menu.style.top = (r.bottom + 4) + 'px'; menu.classList.add('open'); }
  });
  document.addEventListener('click', () => $$('#toolbar .menu-items.open').forEach(x => x.classList.remove('open')));
  $$('[data-export]').forEach(b => b.addEventListener('click', () => doExport(b.dataset.export)));
  $('#btnSeedFrom').addEventListener('click', () => S.project && newProjectDialog(S.project.id));
  $('#btnImport').addEventListener('click', () => $('#importFile').click());
  $('#importFile').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; if (f) doImport(f); });
  $('#btnSearch').addEventListener('click', searchDialog);
  $('#btnSql').addEventListener('click', sqlDialog);
  window.addEventListener('resize', () => requestEdges());
}

async function init() {
  wire();
  try {
    S.schema = await api('GET', '/api/schema');
    await loadProjects();
    const last = localStorage.getItem('flowkb.lastProject');
    const target = S.projects.find(p => String(p.id) === last) || S.projects[0];
    if (target) await openProject(target.id);
    else { renderPanel(); newProjectDialog(); }
  } catch (e) { fail(new Error('Could not reach the Flow KB server: ' + e.message)); }
}
init();
