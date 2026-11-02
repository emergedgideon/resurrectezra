'use strict';
const el = id => document.getElementById(id);
let archiveToken = sessionStorage.getItem('ezra-access-token') || '';
let sources = [];
let selectedSource = new URLSearchParams(location.search).get('source');
let selectedRun = new URLSearchParams(location.search).get('run');
let pageOffset = Math.max(0, (Number(new URLSearchParams(location.search).get('unit')) || 1) - 1);
let sourceDetail = null;
let loadingVersion = 0;
let previewVersion = 0;
let previewURL = null;
let uploading = false;
let refreshing = false;
el('archive-token').value = archiveToken;
function tell(message = '') { el('archive-notice').textContent = message; }
function date(value) { return new Date(value).toLocaleString(); }
function humanSize(bytes) { return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KiB`; }
async function request(path, options = {}, binary = false) {
  const response = await fetch('/api/archive' + path, {...options,
    headers: {...(archiveToken ? {Authorization: 'Bearer ' + archiveToken} : {}), ...options.headers}});
  if (!response.ok) {
    let body = {}; try { body = await response.json(); } catch {}
    if (response.status === 401) el('archive-auth').classList.remove('hidden');
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}).`);
  }
  return binary ? response.blob() : response.json();
}
function drawLibrary() {
  const filter = el('archive-filter').value.toLowerCase();
  const nav = el('source-list'); nav.replaceChildren();
  const filtered = sources.filter(s => s.names.some(n => n.toLowerCase().includes(filter)));
  const active = sources.filter(s => ['queued', 'processing'].includes(s.status)).length;
  el('archive-count').textContent = `${sources.length} preserved originals · ${active} active imports`;
  for (const source of filtered) {
    const button = document.createElement('button'); button.className = 'source-card' + (source.sha256 === selectedSource ? ' selected' : '');
    const title = document.createElement('span'); title.textContent = source.filename;
    const subtitle = document.createElement('span'); subtitle.className = 'source-card-status';
    subtitle.textContent = `${source.status} · ${source.unit_count} passages · ${humanSize(source.size_bytes)}`;
    if (source.warnings.length) subtitle.textContent += ` · ${source.warnings.length} notes`;
    button.append(title, subtitle); button.addEventListener('click', () => openSource(source.sha256).catch(e => tell(e.message))); nav.append(button);
  }
  if (!filtered.length) { const p = document.createElement('p'); p.className = 'muted'; p.textContent = filter ? 'No matching filenames.' : 'No files yet. Import your first sources above.'; nav.append(p); }
}
async function refreshCatalog() {
  sources = await request('/sources'); drawLibrary();
  const inventory = await request('/inventory');
  el('manifest-summary').textContent = `Manifest · ${inventory.received.length}/${inventory.references.length} received`;
  const list = el('manifest-missing'); list.replaceChildren();
  for (const name of inventory.outstanding) { const li = document.createElement('li'); li.textContent = name; list.append(li); }
}
function locationText(unit) {
  const where = unit.location;
  if (where.page) return `Page ${where.page}${unit.kind === 'ocr_page' ? ' · OCR transcription' : ''}`;
  if (where.block) return `Word body block ${where.block} · ${unit.kind}`;
  if (where.frame) return `Image frame ${where.frame} · OCR transcription`;
  if (where.line_start) return `Lines ${where.line_start}–${where.line_end}`;
  return `Record ${where.row || unit.ordinal}`;
}
function updateAddress(ordinal) {
  const params = new URLSearchParams({source: selectedSource, unit: String(ordinal || pageOffset + 1)});
  if (sourceDetail?.selected_run) params.set('run', sourceDetail.selected_run);
  history.replaceState(null, '', '/archive.html?' + params);
}
async function preview(unit) {
  const version = ++previewVersion;
  if (previewURL) { URL.revokeObjectURL(previewURL); previewURL = null; }
  el('source-preview').removeAttribute('src'); el('preview-error').textContent = '';
  const suffix = sourceDetail.source.filename.split('.').pop().toLowerCase();
  const visual = ['pdf', 'png', 'jpg', 'jpeg', 'webp', 'gif', 'tif', 'tiff', 'bmp'].includes(suffix);
  el('preview-panel').classList.toggle('hidden', !visual);
  if (!visual) return;
  el('preview-label').textContent = `${locationText(unit)} · Rendered preview; original unchanged`;
  const sha = selectedSource;
  try {
    const blob = await request(`/sources/${sha}/preview?page=${unit.location.page || 1}`, {}, true);
    if (version !== previewVersion || selectedSource !== sha) return;
    previewURL = URL.createObjectURL(blob); el('source-preview').src = previewURL;
  } catch (error) { if (version === previewVersion) el('preview-error').textContent = error.message; }
}
async function openSource(sha, offset = 0, run = null, selectedOrdinal = null) {
  const version = ++loadingVersion;
  const query = new URLSearchParams({offset: String(offset), limit: '40'}); if (run) query.set('run', run);
  const value = await request(`/sources/${sha}?${query}`);
  if (version !== loadingVersion) return;
  selectedSource = sha; selectedRun = value.selected_run; pageOffset = offset; sourceDetail = value;
  el('source-empty').classList.add('hidden'); el('source-content').classList.remove('hidden');
  const catalog = sources.find(s => s.sha256 === sha);
  el('source-name').textContent = value.source.filename;
  el('source-metadata').textContent = `${humanSize(value.source.size_bytes)} · Imported ${date(value.source.created_at)}${catalog?.names.length > 1 ? ' · Also received as: ' + catalog.names.filter(n => n !== value.source.filename).join(', ') : ''}`;
  el('source-hash').textContent = `SHA-256 · ${sha}`;
  el('source-job').textContent = catalog?.job ? `Import ${catalog.job.status} · Attempt ${catalog.job.attempt}${catalog.job.error ? ' · ' + catalog.job.error : ''}` : 'Initial import retained; reprocess to create a new extraction revision.';
  el('reprocess-source').disabled = ['queued', 'processing'].includes(catalog?.status);
  const select = el('extraction-revision'); select.replaceChildren();
  for (const run of value.runs) {
    const option = document.createElement('option'); option.value = run.id;
    option.textContent = `${date(run.created_at)}${run.id === value.source.current_run ? ' · current' : ' · retained revision'}`;
    option.selected = run.id === value.selected_run; select.append(option);
  }
  const revision = value.runs.find(r => r.id === value.selected_run);
  el('extractor-name').textContent = revision?.extractor || 'Waiting for extraction.';
  const warnings = el('source-warnings'); warnings.replaceChildren();
  for (const warning of revision?.warnings || []) { const li = document.createElement('li'); li.textContent = warning; warnings.append(li); }
  const units = el('source-units'); units.replaceChildren();
  for (const unit of value.units) {
    const article = document.createElement('article'); article.className = 'source-unit'; article.id = 'passage-' + unit.ordinal;
    const top = document.createElement('div'); top.className = 'unit-heading';
    const label = document.createElement('strong'); label.textContent = `#${unit.ordinal} · ${locationText(unit)}`;
    const inspect = document.createElement('button'); inspect.className = 'quiet-button'; inspect.textContent = 'Inspect source';
    inspect.addEventListener('click', () => { updateAddress(unit.ordinal); el('unit-number').value = unit.ordinal; preview(unit); });
    top.append(label, inspect);
    const content = document.createElement('pre'); content.textContent = unit.content || '(No text extracted; inspect the original.)';
    article.append(top, content);
    if (Object.keys(unit.payload).length) {
      const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = 'Preserved fields';
      const payload = document.createElement('pre'); payload.textContent = JSON.stringify(unit.payload, null, 2); details.append(summary, payload); article.append(details);
    }
    units.append(article);
  }
  el('unit-range').textContent = value.total ? `${offset + 1}–${Math.min(offset + 40, value.total)} of ${value.total}` : 'No extracted passages yet';
  el('previous-units').disabled = offset === 0; el('next-units').disabled = offset + 40 >= value.total;
  el('unit-number').max = Math.max(1, value.total); el('unit-number').value = selectedOrdinal || offset + 1;
  const first = value.units.find(u => u.ordinal === selectedOrdinal) || value.units[0];
  updateAddress(first?.ordinal); drawLibrary();
  if (first) await preview(first); else el('preview-panel').classList.add('hidden');
}
async function download(path, filename) {
  const blob = await request(path, {}, true);
  const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename;
  document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
}
el('archive-filter').addEventListener('input', drawLibrary);
el('upload-files').addEventListener('click', async () => {
  if (uploading) return;
  const files = Array.from(el('archive-files').files); if (!files.length) { tell('Choose one or more files first.'); return; }
  uploading = true; el('upload-files').disabled = true; tell();
  let last = null; const outcomes = [];
  try {
    for (let i = 0; i < files.length; i++) {
      el('upload-status').textContent = `Uploading ${i + 1}/${files.length}: ${files[i].name}`;
      try {
        if (files[i].size > 32 * 1024 * 1024) throw new Error('Exceeds the 32 MiB per-file limit.');
        const body = new FormData(); body.append('file', files[i]);
        const result = await request('/uploads', {method: 'POST', body}); last = result.sha256;
        outcomes.push(`${files[i].name}: ${result.duplicate ? 'already preserved; no duplicate created' : 'preserved and queued'}`);
      } catch (error) { outcomes.push(`${files[i].name}: ${error.message}`); }
    }
    el('upload-status').textContent = outcomes.join('\n'); el('archive-files').value = '';
    await refreshCatalog(); if (last) await openSource(last);
  } catch (error) { tell(error.message); }
  finally { uploading = false; el('upload-files').disabled = false; }
});
el('download-original').addEventListener('click', () => download(`/sources/${selectedSource}/original`, sourceDetail.source.filename).catch(e => tell(e.message)));
el('export-archive').addEventListener('click', async () => {
  el('export-archive').disabled = true; tell('Creating a database snapshot and verifying original checksums…');
  try { await download('/export', 'ezra-archive.zip'); tell('Verified archive export downloaded. Store it separately from this machine. Conversations and credentials are not included.'); }
  catch (error) { tell(error.message); }
  finally { el('export-archive').disabled = false; }
});
el('restore-archive').addEventListener('click', async () => {
  const file = el('restore-file').files[0];
  if (!file) { tell('Choose an archive backup ZIP first.'); return; }
  if (sources.length) { tell('This archive already contains sources. Restore will not overwrite it.'); return; }
  if (file.size > 32 * 1024 * 1024) { tell('Backup exceeds the 32 MiB upload limit.'); return; }
  el('restore-archive').disabled = true; tell('Verifying and restoring the archive…');
  try {
    const body = new FormData(); body.append('file', file);
    const result = await request('/restore', {method: 'POST', body});
    await refreshCatalog(); el('restore-file').value = '';
    tell(`Restored ${result.verified_sources} original files and their archive/reconstruction records. Conversations and credentials were not changed.`);
    if (sources[0]) await openSource(sources[0].sha256);
  } catch (error) { tell(error.message); }
  finally { el('restore-archive').disabled = false; }
});
el('export-all').addEventListener('click', async () => {
  el('export-all').disabled = true; tell('Preparing a full backup, including conversations…');
  try {
    const response = await fetch('/api/backup', {headers: archiveToken ? {Authorization: 'Bearer ' + archiveToken} : {}});
    if (!response.ok) { let body = {}; try { body = await response.json(); } catch {} throw new Error(body.detail || 'Full backup failed.'); }
    const url = URL.createObjectURL(await response.blob()); const anchor = document.createElement('a');
    anchor.href = url; anchor.download = 'ezra-full-backup.zip'; document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000); tell('Full backup downloaded: archive, originals, persona state, and conversations. Credentials are excluded.');
  } catch (error) { tell(error.message); }
  finally { el('export-all').disabled = false; }
});
el('reprocess-source').addEventListener('click', async () => {
  try { await request(`/sources/${selectedSource}/reprocess`, {method: 'POST'}); await refreshCatalog(); await openSource(selectedSource, pageOffset, selectedRun); tell('Queued. Existing extraction remains available; the new revision will appear when complete.'); }
  catch (error) { tell(error.message); }
});
el('extraction-revision').addEventListener('change', () => openSource(selectedSource, 0, el('extraction-revision').value).catch(e => tell(e.message)));
el('previous-units').addEventListener('click', () => openSource(selectedSource, Math.max(0, pageOffset - 40), selectedRun).catch(e => tell(e.message)));
el('next-units').addEventListener('click', () => openSource(selectedSource, pageOffset + 40, selectedRun).catch(e => tell(e.message)));
el('go-unit').addEventListener('click', () => {
  const ordinal = Math.max(1, Math.min(sourceDetail.total, Number(el('unit-number').value) || 1));
  openSource(selectedSource, ordinal - 1, selectedRun, ordinal).catch(e => tell(e.message));
});
el('archive-connect').addEventListener('click', () => { archiveToken = el('archive-token').value; sessionStorage.setItem('ezra-access-token', archiveToken); start(); });
async function start() {
  try { await refreshCatalog(); el('archive-auth').classList.add('hidden'); tell(); if (selectedSource) await openSource(selectedSource, pageOffset, selectedRun); }
  catch (error) { tell(error.message); }
}
setInterval(async () => {
  if (refreshing || uploading || !sources.some(s => ['queued', 'processing'].includes(s.status))) return;
  refreshing = true;
  try {
    const prior = sources.find(s => s.sha256 === selectedSource);
    await refreshCatalog(); const current = sources.find(s => s.sha256 === selectedSource);
    if (current && (current.status !== prior?.status || current.current_run !== prior?.current_run)) {
      // Show a completed new revision unless the owner is intentionally browsing an older one.
      const run = selectedRun === prior?.current_run ? null : selectedRun;
      await openSource(selectedSource, pageOffset, run);
    }
  } catch (error) { tell(error.message); }
  finally { refreshing = false; }
}, 1500);
start();
