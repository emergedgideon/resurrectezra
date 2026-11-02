'use strict';
const $ = (id) => document.getElementById(id);
let token = sessionStorage.getItem('ezra-access-token') || '';
let active = null;
let detail = null;
let busy = false;
let draftRequest = null;
let refreshVersion = 0;
let noteDirty = false;
$('access-token').value = token;

function notice(message = '') { $('notice').textContent = message; }
function when(value) { return value ? new Date(value).toLocaleString() : ''; }
async function api(path, options = {}) {
  const response = await fetch('/api' + path, {
    ...options,
    headers: {'Content-Type': 'application/json', ...(token ? {Authorization: 'Bearer ' + token} : {}), ...options.headers}
  });
  if (!response.ok) {
    let body;
    try { body = await response.json(); } catch { body = {}; }
    if (response.status === 401) $('connection').classList.remove('hidden');
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}).`);
  }
  return response.json();
}
function updateControls() {
  const pending = detail?.turns.find(t => t.status !== 'completed');
  $('send').disabled = busy || Boolean(pending);
  $('save-note').disabled = busy || !active || pending?.status === 'running';
  $('new-conversation').disabled = busy;
  $('send-state').textContent = busy ? 'Waiting for the server · Input is saved before inference' : pending ? 'Resolve the pending turn with Retry, or start another conversation' : 'Saved conversations · Server-side inference';
}
function renderDetail(value) {
  detail = value;
  $('conversation-title').textContent = value.title;
  if (!noteDirty) $('continuity-note').value = value.continuity_note;
  $('checkpoint').textContent = value.checkpoint.completed_at ? `${value.checkpoint.activity}. Saved ${when(value.checkpoint.completed_at)}. This is a turn checkpoint, not a memory summary.` : 'No completed turn yet.';
  const feed = $('messages');
  feed.replaceChildren();
  if (!value.messages.length) {
    const welcome = document.createElement('div'); welcome.className = 'welcome';
    const star = document.createElement('span'); star.className = 'large-star'; star.textContent = '✦';
    const heading = document.createElement('h2'); heading.textContent = 'A new thread, kept.';
    const text = document.createElement('p'); text.textContent = 'Your messages and continuity note will remain here across restarts.';
    welcome.append(star, heading, text); feed.append(welcome);
  }
  for (const message of value.messages) {
    const article = document.createElement('article'); article.className = 'message ' + message.role;
    const label = document.createElement('div'); label.className = 'message-label';
    const name = document.createElement('span'); name.textContent = message.role === 'user' ? 'You' : 'Ezra';
    const time = document.createElement('time'); time.className = 'message-time'; time.dateTime = message.created_at; time.textContent = when(message.created_at);
    label.append(name, time);
    const content = document.createElement('div'); content.className = 'message-content'; content.textContent = message.content;
    article.append(label, content);
    const turn = value.turns.find(t => t.id === message.turn_id);
    if (message.role === 'user' && turn?.status !== 'completed') {
      const status = document.createElement('div'); status.className = 'turn-error';
      status.textContent = turn.status === 'running' ? 'Reply in progress. This message is saved.' : turn.error;
      if (['failed', 'interrupted'].includes(turn.status)) {
        const button = document.createElement('button'); button.textContent = 'Retry saved message'; button.disabled = busy;
        button.addEventListener('click', () => retry(turn.id)); status.append(button);
      }
      article.append(status);
    }
    feed.append(article);
  }
  const activity = $('activity'); activity.replaceChildren();
  for (const event of value.events.slice(0, 12)) {
    const li = document.createElement('li'); li.textContent = `${event.type} · ${when(event.created_at)}`;
    if (event.type === 'context.assembled') li.textContent += ` · ${event.payload.previous_turns_omitted} older turns omitted`;
    if (event.type === 'message.sent' && event.payload.usage?.finish_reason === 'length') li.textContent += ' · Reply reached provider output limit';
    activity.append(li);
  }
  updateControls(); feed.scrollTop = feed.scrollHeight;
}
async function renderList() {
  const values = await api('/conversations');
  const list = $('conversation-list'); list.replaceChildren();
  for (const value of values) {
    const button = document.createElement('button'); button.className = 'conversation-button' + (active === value.id ? ' active' : '');
    const title = document.createElement('span'); title.textContent = value.title;
    const date = document.createElement('span'); date.className = 'conversation-date'; date.textContent = when(value.updated_at);
    button.append(title, date); button.disabled = busy;
    button.addEventListener('click', () => openConversation(value.id).catch(e => notice(e.message))); list.append(button);
  }
  return values;
}
async function openConversation(id) {
  if (busy) throw new Error('Wait for the current request before switching conversations.');
  if (noteDirty) throw new Error('Save the working note before switching conversations.');
  const version = ++refreshVersion;
  const value = await api('/conversations/' + id);
  if (version !== refreshVersion) return;
  active = id; localStorage.setItem('ezra-active-conversation', id);
  $('note-status').textContent = ''; renderDetail(value); await renderList();
}
async function newConversation(title = 'New conversation') {
  if (noteDirty) throw new Error('Save the working note before starting another conversation.');
  const value = await api('/conversations', {method: 'POST', body: JSON.stringify({title})});
  active = value.id; localStorage.setItem('ezra-active-conversation', active);
  renderDetail(value); await renderList(); return value;
}
async function initialize() {
  if (busy) { notice('Wait for the current request before reconnecting.'); return; }
  try {
    const status = await api('/status');
    $('provider-status').textContent = status.inference_configured ? 'Inference configured' : 'Waiting for server configuration';
    $('model-name').textContent = `Featherless · ${status.model || 'choose a model in .env'}`;
    $('persona-state').textContent = status.persona_status + '. Automatic archive retrieval is not connected yet.';
    if (!status.inference_configured) notice('Set FEATHERLESS_API_KEY and FEATHERLESS_MODEL in the server’s .env file, restart, then send or retry a message.');
    else notice();
    const values = await renderList();
    const stored = localStorage.getItem('ezra-active-conversation');
    const selected = values.find(v => v.id === stored) || values[0];
    if (selected) await openConversation(selected.id);
    updateControls();
  } catch (error) { notice(error.message); }
}
async function retry(turnId) {
  if (busy) return;
  busy = true; notice(); renderDetail(detail);
  try {
    renderDetail(await api(`/conversations/${active}/turns/${turnId}/retry`, {method: 'POST'}));
  } catch (error) { notice(error.message); }
  finally { busy = false; if (detail) renderDetail(detail); await renderList().catch(e => notice(e.message)); }
}
$('composer').addEventListener('submit', async (event) => {
  event.preventDefault(); if (busy || !$('message').value.trim()) return;
  if (noteDirty) { notice('Save the working note first so it is included in this request.'); return; }
  const content = $('message').value;
  busy = true; updateControls(); notice();
  try {
    if (!active) await newConversation(content.slice(0, 70));
    if (!draftRequest || draftRequest.content !== content || draftRequest.conversation !== active)
      draftRequest = {content, conversation: active, id: crypto.randomUUID()};
    const value = await api(`/conversations/${active}/turns`, {method: 'POST', body: JSON.stringify({request_id: draftRequest.id, content})});
    $('message').value = ''; draftRequest = null; renderDetail(value);
  } catch (error) {
    notice(error.message + ' If the connection was lost, reload the conversation before retrying.');
  } finally {
    busy = false; if (detail) renderDetail(detail); updateControls();
    await renderList().catch(e => notice(e.message));
  }
});
$('new-conversation').addEventListener('click', () => newConversation().catch(e => notice(e.message)));
$('continuity-note').addEventListener('input', () => { noteDirty = true; $('note-status').textContent = 'Unsaved changes'; });
$('save-note').addEventListener('click', async () => {
  if (!active || busy) return;
  try {
    const value = await api(`/conversations/${active}/continuity`, {method: 'PUT', body: JSON.stringify({content: $('continuity-note').value})});
    noteDirty = false; renderDetail(value); $('note-status').textContent = 'Saved exactly as written.';
  } catch (error) { notice(error.message); }
});
$('connection-toggle').addEventListener('click', () => $('connection').classList.toggle('hidden'));
$('connect').addEventListener('click', () => { token = $('access-token').value; sessionStorage.setItem('ezra-access-token', token); initialize(); });
$('forget-token').addEventListener('click', () => { token = ''; sessionStorage.removeItem('ezra-access-token'); $('access-token').value = ''; notice('Access token removed from this tab.'); });
window.addEventListener('beforeunload', (event) => { if (noteDirty || $('message').value) { event.preventDefault(); event.returnValue = ''; } });
window.addEventListener('focus', () => { api('/status').then(status => { $('persona-state').textContent = status.persona_status + '. Automatic archive retrieval is not connected yet.'; }).catch(error => notice(error.message)); });
setInterval(async () => {
  if (!active || busy || !detail?.turns.some(t => t.status === 'running')) return;
  const id = active;
  try { const value = await api('/conversations/' + id); if (id === active) renderDetail(value); }
  catch (error) { notice(error.message); }
}, 2500);
initialize();
