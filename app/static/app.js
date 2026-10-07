const $ = (id) => document.getElementById(id);
const fieldNames = {
  agreement_value: 'Agreement value', agreement_start_date: 'Start date',
  agreement_end_date: 'End date', renewal_notice_days: 'Notice period',
  party_one: 'Party one', party_two: 'Party two',
};
const csvNames = ['File Name', 'Aggrement Value', 'Aggrement Start Date', 'Aggrement End Date', 'Renewal Notice (Days)', 'Party One', 'Party Two'];
let files = [], activeId = null, apiKey = '', provider = 'openai', model = 'gpt-4.1-mini', config = null, busy = false, tab = 'details';
let toastTimer;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function current() { return files.find((item) => item.id === activeId); }
function toast(message) {
  $('toast').textContent = message; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 6000);
}
function connection() {
  const ready = Boolean(apiKey || config?.providers?.[provider]?.configured);
  $('connection-label').textContent = ready ? `${config?.providers?.[provider]?.label || provider} · Key configured` : 'Connect AI';
  $('connection-dot').classList.toggle('ready', ready);
  $('privacy-provider').textContent = config?.providers?.[provider]?.label || provider;
}
function updateProviderHelp() {
  const selected = $('provider-input').value;
  $('key-help').textContent = config?.providers?.[selected]?.configured ? 'A server key for this provider is configured. Leave blank to use it.' : 'Kept in this page’s memory only. Cleared when you reload.';
  $('api-key').placeholder = selected === 'groq' ? 'gsk_…' : 'sk-…';
  $('model-help').textContent = selected === 'groq' ? 'qwen/qwen3.8-27b supports text and images. Long scans are read in batches.' : 'Use an OpenAI model with image input and structured output support.';
}
function openSettings() {
  $('provider-input').value = provider; $('api-key').value = apiKey; $('model-input').value = model;
  updateProviderHelp(); $('settings-dialog').showModal();
}
function switchTab(next) {
  tab = next;
  for (const button of document.querySelectorAll('[data-tab]')) {
    const selected = button.dataset.tab === tab;
    button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
    $(`view-${button.dataset.tab}`).hidden = !selected;
  }
  if (tab === 'source') loadPreview(current());
}
function addFiles(uploaded) {
  const supported = Object.values(config?.formats || {}).flat();
  for (const file of uploaded) {
    if (files.length >= 20) { toast('Keep up to 20 documents in this workspace. Clear files to add more.'); break; }
    const extension = '.' + file.name.split('.').pop().toLowerCase();
    if (supported.length && !supported.includes(extension)) { toast(`${file.name}: unsupported format. Export it as PDF or a supported format.`); continue; }
    if (file.size > 20 * 1024 * 1024) { toast(`${file.name} exceeds the 20 MB limit.`); continue; }
    if (!file.size) { toast(`${file.name} is empty.`); continue; }
    if (files.some((item) => item.file.name === file.name && item.file.size === file.size && item.file.lastModified === file.lastModified)) continue;
    const item = { id: crypto.randomUUID(), file, state: 'ready', result: null, error: '', preview: null, previewError: '', previewLoading: false };
    files.push(item); if (!activeId) activeId = item.id;
  }
  render(); if (tab === 'source') loadPreview(current());
}
function renderQueue() {
  $('settings-open').disabled = busy;
  $('file-count').textContent = files.length;
  $('clear-all').hidden = !files.length; $('clear-all').disabled = busy;
  $('queue-empty').hidden = Boolean(files.length); $('file-list').replaceChildren();
  for (const item of files) {
    const row = node('div', undefined, 'file-row' + (item.id === activeId ? ' active' : ''));
    const select = node('button', undefined, 'file-select'); select.title = item.file.name;
    select.setAttribute('aria-label', `Select ${item.file.name}`);
    select.setAttribute('aria-pressed', String(item.id === activeId));
    select.onclick = () => { activeId = item.id; render(); if (tab === 'source') loadPreview(item); };
    const info = node('span', undefined, 'file-info');
    info.append(node('span', item.file.name, 'file-name'));
    const state = { ready: 'Ready to extract', working: 'Extracting…', done: 'Details extracted', error: 'Needs attention' }[item.state];
    info.append(node('span', `${(item.file.size / 1024).toFixed(0)} KB · ${state}`, `file-state ${item.state}`));
    select.append(node('span', item.file.name.split('.').pop().slice(0, 4), 'file-icon'), info);
    const remove = node('button', '×', 'remove-file'); remove.setAttribute('aria-label', `Remove ${item.file.name}`); remove.disabled = busy;
    remove.onclick = () => { files = files.filter((f) => f.id !== item.id); if (activeId === item.id) activeId = files[0]?.id || null; render(); if (tab === 'source') loadPreview(current()); };
    row.append(select, remove); $('file-list').append(row);
  }
  const pending = files.filter((f) => f.state !== 'done').length;
  $('extract-all').disabled = busy || !pending;
  $('extract-all').textContent = busy ? 'Extracting documents…' : pending > 1 ? `Extract ${pending} documents ↗` : 'Extract details ↗';
}
function render() {
  renderQueue();
  const item = current();
  $('active-title').textContent = item ? item.file.name : 'A clearer view of every agreement';
  $('active-meta').textContent = item ? `${item.file.name.split('.').pop().toUpperCase()} · ${(item.file.size / 1024).toFixed(0)} KB · ${item.result ? 'Extraction complete' : 'Ready for your review'}` : 'Upload a document to get started';
  $('export-button').disabled = !item?.result;
  $('empty-state').hidden = Boolean(item?.result);
  $('results').hidden = !item?.result;
  $('results').replaceChildren();
  $('notice').hidden = true;
  if (item?.state === 'working') {
    $('notice').replaceChildren(node('span', '', 'spinner'), node('span', 'Reading the document and extracting details. Long scans may take several minutes.'));
    $('notice').className = 'notice'; $('notice').hidden = false;
  } else if (item?.error) {
    $('notice').textContent = item.error; $('notice').className = 'notice error'; $('notice').hidden = false;
  } else if (item && !item.result) {
    $('notice').textContent = 'Your document is ready. Preview the source, or extract its details.';
    $('notice').className = 'notice'; $('notice').hidden = false;
  }
  $('result-status').textContent = item?.result ? `${Object.keys(fieldNames).filter((k) => item.result[k].value !== null).length} of 6 fields found` : '6 fields to uncover';
  if (item?.result) renderResults(item);
  renderSource(item);
  $('view-json').replaceChildren(item?.result ? node('pre', JSON.stringify({filename: item.file.name, provider: item.provider, model: item.model, result: item.result}, null, 2)) : node('p', 'Extract a document to see its structured output.', 'placeholder'));
}
function renderResults(item) {
  const result = item.result;
  const summary = node('div', undefined, 'summary-card'); summary.append(node('h3', result.document_type), node('p', result.summary));
  const grid = node('div', undefined, 'result-grid');
  for (const [key, label] of Object.entries(fieldNames)) {
    const field = result[key], card = node('article', undefined, 'field-card');
    const top = node('div', undefined, 'field-top'); top.append(node('span', label, 'field-label'), node('span', field.status, `badge ${field.status}`));
    let value = field.value ?? 'Not found';
    if (field.value !== null && key === 'agreement_value' && result.currency) value = `${result.currency} ${field.value}`;
    if (field.value !== null && key === 'renewal_notice_days') value += ' days';
    card.append(top, node('div', value, `field-value ${field.status}`));
    const evidence = node('details'); evidence.append(node('summary', field.evidence ? 'View supporting text' : 'View note'));
    if (field.evidence) evidence.append(node('blockquote', field.evidence));
    evidence.append(node('p', field.explanation)); card.append(evidence); grid.append(card);
  }
  $('results').append(summary, grid);
  if (result.warnings.length) {
    const warning = node('div', undefined, 'warnings'), list = node('ul');
    warning.append(node('strong', 'A few things to review'));
    for (const text of result.warnings) list.append(node('li', text));
    warning.append(list); $('results').append(warning);
  }
  const actions = node('div', undefined, 'result-actions'), again = node('button', 'Extract again', 'secondary');
  again.disabled = busy; again.onclick = () => extractBatch([item]); actions.append(again); $('results').append(actions);
}
async function responseJSON(response) {
  let data;
  try { data = await response.json(); } catch { throw new Error('The server returned an unreadable response. Please retry.'); }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The request could not be processed. Check the file and try again.');
  return data;
}
async function loadPreview(item) {
  if (!item || item.preview || item.previewLoading || item.previewError) return;
  item.previewLoading = true; renderSource(item);
  try {
    const body = new FormData(); body.append('file', item.file);
    item.preview = await responseJSON(await fetch('/api/preview', {method: 'POST', body}));
  } catch (error) { item.previewError = error.message; }
  finally { item.previewLoading = false; if (current()?.id === item.id) renderSource(item); }
}
function renderSource(item) {
  const view = $('view-source'); view.replaceChildren();
  if (!item) { view.append(node('p', 'Upload a file to preview its contents.', 'placeholder')); return; }
  if (item.previewLoading) { view.append(node('p', 'Preparing your document preview…', 'placeholder')); return; }
  if (item.previewError) {
    view.append(node('p', item.previewError, 'placeholder'));
    const retry = node('button', 'Retry preview', 'secondary'); retry.onclick = () => { item.previewError = ''; loadPreview(item); }; view.append(retry); return;
  }
  if (!item.preview) { view.append(node('p', 'Open this tab to load a document preview.', 'placeholder')); return; }
  for (const warning of item.preview.warnings) view.append(node('p', warning, 'source-label'));
  if (item.preview.text) { view.append(node('p', 'Document text', 'source-label'), node('pre', item.preview.text)); }
  item.preview.images.forEach((src, i) => {
    view.append(node('p', `Image section ${i + 1}`, 'source-label'));
    const image = node('img'); image.src = src; image.alt = `Document image section ${i + 1}`; image.loading = 'lazy'; view.append(image);
  });
}
async function extractBatch(items) {
  if (busy) return;
  if (!apiKey && !config?.providers?.[provider]?.configured) { openSettings(); return; }
  busy = true; render();
  const keyForRun = apiKey, modelForRun = model, providerForRun = provider;
  try {
    for (const item of items) {
      item.state = 'working'; item.error = ''; render();
      try {
        const body = new FormData(); body.append('file', item.file); body.append('model', modelForRun); body.append('provider', providerForRun);
        const headers = keyForRun ? {'X-API-Key': keyForRun} : {};
        const data = await responseJSON(await fetch('/api/extract', {method: 'POST', headers, body}));
        item.result = data.result; item.provider = data.provider || providerForRun; item.model = data.model; item.state = 'done';
      } catch (error) { item.state = 'error'; item.error = error.message; }
      render();
    }
  } finally { busy = false; render(); }
}
function download(name, data, type) {
  const url = URL.createObjectURL(new Blob([data], {type}));
  const link = document.createElement('a'); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function csvCell(value) {
  let text = String(value ?? '');
  // Prevent model/document text becoming a formula when opened in a spreadsheet.
  if (/^[\s]*[=+@-]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}
$('dropzone').onclick = () => $('file-input').click();
$('file-input').onchange = (event) => { addFiles(event.target.files); event.target.value = ''; };
for (const name of ['dragenter', 'dragover']) $('dropzone').addEventListener(name, (e) => { e.preventDefault(); $('dropzone').classList.add('dragging'); });
for (const name of ['dragleave', 'drop']) $('dropzone').addEventListener(name, (e) => { e.preventDefault(); $('dropzone').classList.remove('dragging'); });
$('dropzone').addEventListener('drop', (e) => addFiles(e.dataTransfer.files));
document.addEventListener('dragover', (e) => e.preventDefault());
document.addEventListener('drop', (e) => e.preventDefault());
$('clear-all').onclick = () => { if (!busy) { files = []; activeId = null; render(); } };
$('extract-all').onclick = () => extractBatch(files.filter((item) => item.state !== 'done'));
for (const button of document.querySelectorAll('[data-tab]')) {
  button.onclick = () => switchTab(button.dataset.tab);
  button.onkeydown = (event) => {
    const tabs = ['details', 'source', 'json']; let index = tabs.indexOf(tab);
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    index = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3;
    switchTab(tabs[index]); $(`tab-${tabs[index]}`).focus();
  };
}
$('settings-open').onclick = openSettings;
$('provider-input').onchange = () => {
  const selected = $('provider-input').value;
  // Never reuse one provider's credential when switching to another provider.
  $('api-key').value = selected === provider ? apiKey : '';
  $('model-input').value = selected === provider ? model : config?.providers?.[selected]?.model || (selected === 'groq' ? 'qwen/qwen3.8-27b' : 'gpt-4.1-mini');
  updateProviderHelp();
};
$('settings-close').onclick = () => $('settings-dialog').close();
$('settings-dialog').addEventListener('close', () => { $('api-key').value = ''; });
$('settings-form').onsubmit = (event) => {
  event.preventDefault();
  const selected = $('provider-input').value, enteredKey = $('api-key').value.trim();
  if (selected === 'openai' && enteredKey.startsWith('gsk_')) { toast('This looks like a Groq key. Choose Groq in the Provider menu.'); return; }
  if (selected === 'groq' && enteredKey.startsWith('sk-')) { toast('This looks like an OpenAI key. Choose OpenAI in the Provider menu.'); return; }
  provider = selected; apiKey = enteredKey;
  model = $('model-input').value.trim() || config?.providers?.[provider]?.model;
  $('api-key').value = '';
  connection(); $('settings-dialog').close(); toast('Settings saved for this page. Select Extract details to continue.');
};
$('forget-key').onclick = () => { apiKey = ''; $('api-key').value = ''; connection(); toast(config?.providers?.[provider]?.configured ? 'Entered key cleared. The server key is still configured.' : 'API key forgotten.'); };
$('export-button').onclick = () => $('export-dialog').showModal();
$('export-close').onclick = () => $('export-dialog').close();
$('export-json').onclick = () => {
  const item = current(); if (!item?.result) return;
  download(item.file.name + '.json', JSON.stringify({filename: item.file.name, provider: item.provider, model: item.model, result: item.result}, null, 2), 'application/json'); $('export-dialog').close();
};
$('export-csv').onclick = () => {
  const rows = [csvNames, ...files.filter((f) => f.result).map((item) => [item.file.name, ...Object.keys(fieldNames).map((key) => item.result[key].value)])];
  download('agreement-extractions.csv', '\ufeff' + rows.map((row) => row.map(csvCell).join(',')).join('\r\n'), 'text/csv;charset=utf-8'); $('export-dialog').close();
};
fetch('/api/config').then(responseJSON).then((data) => {
  config = data; provider = data.provider; model = data.model; $('model-input').value = model; $('provider-input').value = provider;
  $('file-input').accept = Object.values(data.formats).flat().join(',');
  $('formats-list').textContent = Object.entries(data.formats).map(([group, formats]) => `${group}: ${formats.join(', ')}`).join(' · ');
  connection();
}).catch(() => { $('connection-label').textContent = 'Server unavailable'; $('formats-list').textContent = 'Start the application server to load supported formats.'; toast('Could not reach the server. Reload after starting the app.'); });
render();
