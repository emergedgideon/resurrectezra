'use strict';
const ui = id => document.getElementById(id);
let token = sessionStorage.getItem('ezra-access-token') || '';
let offset = 0, total = 0, queryVersion = 0, recordRequest = 0, personaRequest = 0;
let record = null, version = null, body = {}, persona = null, report = null, dirty = false, saving = false;
const selected = new Map();
ui('recon-token').value = token;
function notice(text = '') { ui('recon-notice').textContent = text; }
function node(tag, text, css) { const n = document.createElement(tag); n.textContent = text; if (css) n.className = css; return n; }
function sourceLink(text, href) { const n = node('a', text); n.href = href; n.target = '_blank'; n.rel = 'noopener'; return n; }
function date(value) { return new Date(value).toLocaleString(); }
function safe(task) { return async () => { try { await task(); } catch (e) { notice(e.message); } }; }
async function api(path, options = {}) {
  const response = await fetch('/api' + path, {...options, headers: {'Content-Type': 'application/json', ...(token ? {Authorization: 'Bearer ' + token} : {}), ...options.headers}});
  if (!response.ok) { let value = {}; try { value = await response.json(); } catch {} if (response.status === 401) ui('recon-auth').classList.remove('hidden'); throw new Error(typeof value.detail === 'string' ? value.detail : `Request failed (${response.status}).`); }
  return response.json();
}
function selection() {
  ui('selected-count').textContent = `${selected.size} selected record revisions`; const list = ui('selected-records'); list.replaceChildren();
  for (const [id, title] of selected) { const li = node('li', title + ' '), remove = node('button', 'Remove'); remove.onclick = () => { selected.delete(id); selection(); }; li.append(remove); list.append(li); }
}
async function loadRecords() {
  const request = ++queryVersion;
  const p = new URLSearchParams({offset: String(offset), limit: '30', q: ui('record-search').value});
  if (ui('record-kind').value) p.set('kind', ui('record-kind').value);
  const result = await api('/reconstruction/records?' + p); if (request !== queryVersion) return;
  total = result.total; ui('record-count').textContent = `${total} records in this view`;
  const list = ui('record-list'); list.replaceChildren();
  for (const item of result.records) {
    const button = node('button', '', 'source-card' + (item.id === record?.id ? ' selected' : ''));
    button.append(node('span', item.title), node('span', `${item.kind} · ${item.origin} · ${item.status} · r${item.revision}`, 'source-card-status'));
    if (item.dates.event_start || item.dates.record_date) button.append(node('span', item.dates.event_start ? 'Event claim: ' + item.dates.event_start : 'Record date: ' + item.dates.record_date + ' · event unverified', 'source-card-status'));
    button.onclick = safe(() => openRecord(item.id)); list.append(button);
  }
  ui('records-page').textContent = total ? `${offset + 1}–${Math.min(offset + 30, total)}` : '0';
  ui('records-prev').disabled = offset === 0; ui('records-next').disabled = offset + 30 >= total;
}
function fillRecord(revision) {
  version = revision; body = structuredClone(revision.body);
  ui('record-title').value = body.title; ui('edit-kind').value = body.kind; ui('record-origin').value = body.origin;
  ui('record-status').value = body.status; ui('record-text').value = body.text; ui('record-tags').value = body.tags.join('|');
  ui('record-dates').value = JSON.stringify(body.dates, null, 2); ui('record-notes').value = body.notes; ui('record-citations').value = JSON.stringify(body.citations, null, 2);
  const evidence = ui('record-evidence'); evidence.replaceChildren(node('h3', 'Pinned source evidence'));
  for (const citation of body.citations) { const card = document.createElement('details'); card.open = body.citations.length === 1; card.append(node('summary', `${citation.filename} · passage ${citation.ordinal} · ${citation.field}`), sourceLink('Open exact source location ↗', citation.href), node('pre', citation.quote)); evidence.append(card); }
  if (!body.citations.length) evidence.append(node('p', 'Explicit owner addition; no source claim is implied.', 'muted'));
  dirty = false;
}
async function openRecord(id) {
  if (dirty) throw new Error('Save the record before switching, or reload to discard unsaved changes.');
  const request = ++recordRequest;
  const result = await api('/reconstruction/records/' + id);
  if (request !== recordRequest || dirty) return;
  record = result; ui('record-heading').textContent = record.current.body.title;
  const history = ui('record-history'); history.replaceChildren();
  for (const item of record.revisions) { const option = node('option', `Revision ${item.revision} · ${item.author} · ${date(item.created_at)}`); option.value = item.id; history.append(option); }
  fillRecord(record.current);
  const relations = ui('record-relations'); relations.replaceChildren();
  for (const relation of record.relations) relations.append(node('p', `${relation.kind} · ${relation.left_id === id ? relation.right_id : relation.left_id}\n${relation.note}`));
  window.history.replaceState(null, '', '/reconstruction.html?record=' + id); await loadRecords();
}
function newRecord() {
  if (dirty) throw new Error('Save the current revision before starting another record.');
  ++recordRequest; record = null; version = null; ui('record-heading').textContent = 'Explicit owner addition'; ui('record-history').replaceChildren(node('option', 'New record'));
  fillRecord({body: {title: '', text: '', kind: 'identity', origin: 'owner_statement', status: 'proposed', tags: [], facets: ['identity'], dates: {}, notes: '', citations: []}});
  ui('record-relations').replaceChildren();
}
ui('record-form').addEventListener('input', () => { dirty = true; });
ui('record-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (saving) return;
  saving = true; ui('save-record').disabled = true;
  try {
    // Textareas expose LF newlines. Retain the exact source string when the displayed
    // wording was not edited, including original CRLF/CR sequences.
    const exactIfUnchanged = (value, original) => value === original.replace(/\r\n?/g, '\n') ? original : value;
    const newKind = ui('edit-kind').value;
    const updated = {...body, title: ui('record-title').value, kind: newKind, facets: newKind === body.kind ? body.facets : body.facets.filter(f => f !== body.kind), origin: ui('record-origin').value, status: ui('record-status').value,
      text: exactIfUnchanged(ui('record-text').value, body.text), tags: ui('record-tags').value.split('|').filter(Boolean), dates: JSON.parse(ui('record-dates').value), notes: exactIfUnchanged(ui('record-notes').value, body.notes), citations: JSON.parse(ui('record-citations').value)};
    const value = await api('/reconstruction/records' + (record ? '/' + record.id : ''), {method: record ? 'PUT' : 'POST', body: JSON.stringify({body: updated, expected_revision: record?.current.revision})});
    dirty = false; await openRecord(value.id); notice('Saved as a new attributable revision. Earlier wording remains available.');
  } catch (e) { notice(e.message); }
  finally { saving = false; ui('save-record').disabled = false; }
});
ui('record-history').onchange = () => { if (dirty) { notice('Save changes before opening another revision.'); return; } const item = record?.revisions.find(r => r.id === ui('record-history').value); if (item) fillRecord(item); };
ui('attach-citation').onclick = safe(async () => {
  const p = new URL(ui('citation-url').value, location.origin).searchParams, sha = p.get('source'), run = p.get('run'), ordinal = Number(p.get('unit') || 1);
  if (!sha || !run || ordinal < 1) throw new Error('Use a source link containing source, run, and unit.');
  const source = await api(`/archive/sources/${sha}?run=${encodeURIComponent(run)}&offset=${ordinal - 1}&limit=1`), unit = source.units[0], field = ui('citation-field').value;
  const text = field === '$content' ? unit?.content : unit?.payload[field]; if (typeof text !== 'string' || !text.length) throw new Error('This source field has no text.');
  const citations = JSON.parse(ui('record-citations').value); citations.push({sha256: sha, run_id: run, ordinal, field, start: 0, end: Array.from(text).length, quote: text});
  if (!ui('record-text').value) { body.text = text; ui('record-text').value = text; ui('record-origin').value = 'source_statement'; }
  ui('record-citations').value = JSON.stringify(citations, null, 2); dirty = true; notice('Exact evidence attached. Save to validate and pin it.');
});
ui('select-record').onclick = () => { if (!record || dirty) { notice('Save the record before selecting a revision.'); return; } selected.set(version.id, version.body.title); selection(); };
ui('new-record').onclick = safe(newRecord);
ui('link-records').onclick = safe(async () => { if (!record) throw new Error('Save or open a record first.'); await api('/reconstruction/relations', {method: 'POST', body: JSON.stringify({left_id: record.id, right_id: ui('relation-other').value, kind: ui('relation-kind').value, note: ui('relation-note').value})}); await openRecord(record.id); notice('Relationship recorded. Both accounts remain intact.'); });
async function showPersona(id) { const request = ++personaRequest; ui('activate-persona').disabled = true; const result = await api('/personas/' + id); if (request !== personaRequest) return; persona = result; ui('persona-preview').textContent = persona.compiled_text; ui('persona-attribution').textContent = `${persona.author} · ${date(persona.created_at)} · ${Array.from(persona.compiled_text).length} characters · ${persona.items.length} pinned records`; ui('activate-persona').disabled = false; }
async function loadPersonas(preferred) {
  const result = await api('/personas'), history = ui('persona-history'), prior = preferred || history.value || result.active_id; history.replaceChildren();
  ui('active-persona').textContent = result.active_id ? 'Active persona revision: ' + result.active_id : 'No persona is activated';
  for (const item of result.revisions) { const option = node('option', item.title + (item.id === result.active_id ? ' · active' : '')); option.value = item.id; history.append(option); }
  if (result.revisions.some(r => r.id === prior)) history.value = prior;
  const events = ui('persona-events'); events.replaceChildren(); for (const event of result.events.slice(0, 8)) events.append(node('p', `${event.action} · ${date(event.created_at)} · ${event.author}`));
  if (history.value) await showPersona(history.value); else { persona = null; ui('activate-persona').disabled = true; }
}
ui('save-persona').onclick = safe(async () => { const result = await api('/personas', {method: 'POST', body: JSON.stringify({title: ui('persona-title').value, revisions: Array.from(selected.keys()), instructions: ui('persona-instructions').value, parent_id: persona?.id || null})}); await loadPersonas(result.id); notice('Persona draft saved. It has not been activated.'); });
ui('persona-history').onchange = safe(() => showPersona(ui('persona-history').value));
ui('activate-persona').onclick = safe(async () => { await api('/personas/' + persona.id + '/activate', {method: 'POST'}); await loadPersonas(persona.id); notice('This exact persona revision is active for future requests.'); });
ui('deactivate-persona').onclick = safe(async () => { await api('/personas/deactivate', {method: 'POST'}); await loadPersonas(); notice('Persona deactivated. All revisions are retained.'); });
async function loadReport() {
  report = await api('/reconstruction/reconciliation'); const list = ui('reconciliation-list'); list.replaceChildren();
  if (!report) { ui('reconciliation-summary').textContent = 'No report yet. Run a source comparison above.'; return; }
  ui('reconciliation-summary').textContent = `${report.ledger_count} ledger records · ${report.pdf_pages} PDF pages · ${report.consolidated_count} consolidated records. ${JSON.stringify(report.counts)}. ${report.limitations}`;
  for (const mapping of report.mappings) {
    const details = document.createElement('details'); details.append(node('summary', `${mapping.ledger_id} · ${mapping.pdf_status} · review: ${mapping.review_status}`), sourceLink('Ledger source ↗', mapping.ledger.href), node('p', `Record date: ${mapping.record_date || 'unknown'}; event date unverified. Inclusion flag: ${mapping.inclusion_claim}`, 'muted'));
    for (const c of mapping.pdf_candidates) details.append(sourceLink('PDF passage ' + c.ordinal + ' ↗', c.href));
    for (const c of mapping.consolidated_candidates) details.append(sourceLink(`${c.memory_id} · suggestion score ${c.score} ↗`, c.href));
    const status = document.createElement('select'); status.setAttribute('aria-label', mapping.ledger_id + ' review status'); for (const state of ['unresolved', 'verified', 'rejected']) { const option = node('option', state); option.value = state; status.append(option); }
    const notes = document.createElement('textarea'); notes.rows = 2; notes.placeholder = 'Review explanation'; notes.setAttribute('aria-label', mapping.ledger_id + ' review notes');
    const citations = document.createElement('textarea'); citations.rows = 2; citations.value = '[]'; citations.setAttribute('aria-label', mapping.ledger_id + ' evidence JSON');
    const save = node('button', 'Save review'); save.onclick = safe(async () => { await api(`/reconstruction/reconciliation/${report.id}/${mapping.mapping_id || mapping.ledger_id}/reviews`, {method: 'POST', body: JSON.stringify({status: status.value, notes: notes.value, citations: JSON.parse(citations.value)})}); await loadReport(); notice('Review appended; previous review history remains stored.'); });
    details.append(node('p', 'Verified mappings require exact evidence beyond the ledger. Paste citation JSON from a record; suggestions alone are insufficient.', 'muted'), status, notes, citations, save);
    if (mapping.latest_review) details.append(node('p', mapping.latest_review.body.notes, 'muted'));
    const reviews = (report.reviews || []).filter(r => r.ledger_id === (mapping.mapping_id || mapping.ledger_id));
    if (reviews.length) { const history = document.createElement('details'); history.append(node('summary', 'Review history')); for (const review of reviews) history.append(node('p', `${review.body.status} · ${review.author} · ${date(review.created_at)}\n${review.body.notes}`)); details.append(history); }
    list.append(details);
  }
}
ui('seed-records').onclick = safe(async () => { ui('seed-records').disabled = true; try { const result = await api('/reconstruction/bootstrap', {method: 'POST'}); await loadRecords(); await loadPersonas(); notice(`${result.indexed_candidates} archive candidates indexed. ${result.note}`); } finally { ui('seed-records').disabled = false; } });
ui('run-reconciliation').onclick = safe(async () => { ui('run-reconciliation').disabled = true; try { await api('/reconstruction/reconciliation', {method: 'POST'}); await loadReport(); notice('Comparison saved. Machine correspondences remain unreviewed.'); } finally { ui('run-reconciliation').disabled = false; } });
ui('record-kind').onchange = safe(async () => { offset = 0; await loadRecords(); });
let searchTimer; ui('record-search').oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(safe(async () => { offset = 0; await loadRecords(); }), 250); };
ui('records-prev').onclick = safe(async () => { offset = Math.max(0, offset - 30); await loadRecords(); }); ui('records-next').onclick = safe(async () => { offset += 30; await loadRecords(); });
ui('recon-connect').onclick = () => { token = ui('recon-token').value; sessionStorage.setItem('ezra-access-token', token); start(); };
window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
async function start() { ui('record-fields').disabled = true; try { await loadRecords(); await loadPersonas(); await loadReport(); const id = new URLSearchParams(location.search).get('record'); if (id) await openRecord(id); else newRecord(); ui('recon-auth').classList.add('hidden'); ui('record-fields').disabled = false; } catch (e) { notice(e.message); } }
start();
