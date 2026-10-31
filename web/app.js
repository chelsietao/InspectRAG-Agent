import {safeSourceUrl, latestForImage, analysisOf, referencesOf, latestReferences, canDraft,
  statuses, kinds, errorText, samePending, memoryAnchor, hasRetractedObservation} from './ui-core.mjs';

const $ = id => document.getElementById(id);
const state = {cases: [], caseId: null, imageId: null, images: [], runs: [], reports: [],
  answerId: null, timer: null, sequence: 0, busy: false, reportSignature: null,
  facts: [], factSignature: null, memorySourceId: '', previewSequence: 0};
const retryKeys = new Map();
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
};
const short = value => value?.slice(0, 7) || '';
const base = (caseId = state.caseId) => `/cases/${encodeURIComponent(caseId)}`;
const runBase = run => `${base(run.case_id)}/runs/${encodeURIComponent(run.id)}`;
const imageUrl = image => `${base(image.case_id)}/images/${encodeURIComponent(image.id)}`;
const dateText = value => new Date(value).toLocaleString('zh-TW', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false});
function notice(text, success = false) {
  $('notice').textContent = text;
  $('notice').classList.toggle('success', success);
  $('notice').hidden = !text;
}
function connection(online) {
  $('service-label').textContent = online ? '本機服務已連線' : '無法連線，請確認服務已啟動';
  $('service-dot').className = `status-dot ${online ? 'online' : 'offline'}`;
}
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, {cache: 'no-store', ...options}); }
  catch { connection(false); throw new Error('network_error'); }
  connection(true);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === 'string' ? payload.detail : 'invalid_request');
  }
  return response.json();
}
const post = (path, body) => api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
function showError(error) {
  notice(error.message === 'network_error'
    ? '連線中斷，請確認本機服務已啟動，再重新整理紀錄，相同操作重送時會沿用尚未取得回覆的請求編號。'
    : errorText(error.message));
}
async function action(callback) {
  if (state.busy) return;
  state.busy = true;
  updateButtons();
  try { await callback(); }
  catch (error) { showError(error); }
  finally { state.busy = false; updateButtons(); }
}
function updateButtons() {
  const selected = Boolean(state.imageId);
  $('analyze').disabled = state.busy || !selected || samePending(state.runs, 'analysis', state.imageId);
  $('find-references').disabled = state.busy || !selected || samePending(state.runs, 'references', state.imageId);
  $('ask').disabled = state.busy || !state.caseId;
  $('load-sample').disabled = state.busy || !state.caseId;
  $('upload-input').disabled = state.busy || !state.caseId;
  const selectedAnswer = state.runs.find(run => run.id === state.answerId);
  $('draft-report').disabled = state.busy || !canDraft(selectedAnswer) || hasRetractedObservation(selectedAnswer?.result, state.facts);
  $('save-fact').disabled = state.busy || !state.caseId || !$('fact-confirm').checked || ($('fact-image-scope').checked && !selected);
  $('memory-source').disabled = !$('use-memory').checked;
  $('new-case-form').querySelector('button').disabled = state.busy;
  for (const button of $('case-list').querySelectorAll('button')) button.disabled = state.busy;
}
function renderCases() {
  $('case-count').textContent = state.cases.length;
  $('case-list').replaceChildren();
  if (!state.cases.length) $('case-list').append(el('p', 'sidebar-hint', '第一個案件，從上方建立。'));
  for (const item of [...state.cases].reverse()) {
    const button = el('button', 'case-button');
    button.type = 'button';
    button.setAttribute('aria-current', String(item.id === state.caseId));
    button.append(el('strong', '', item.title), el('small', '', `${dateText(item.created_at)} · ${short(item.id)}`));
    button.addEventListener('click', () => selectCase(item.id));
    $('case-list').append(button);
  }
  updateButtons();
}
async function loadCases(preferred) {
  const response = await api('/cases');
  state.cases = response.items;
  const id = preferred || state.caseId || new URLSearchParams(location.search).get('case');
  const chosen = state.cases.find(item => item.id === id) || state.cases.at(-1);
  renderCases();
  if (chosen) await selectCase(chosen.id);
  else {
    state.caseId = null;
    $('welcome').hidden = false;
    $('case-workspace').hidden = true;
  }
}
async function selectCase(id) {
  if (id === state.caseId) { renderCases(); await refreshCase(); return; }
  $('question').value = '';
  $('include-image').checked = true;
  $('use-memory').checked = true;
  $('fact-text').value = ''; $('fact-confirm').checked = false;
  $('fact-image-scope').checked = true;
  state.memorySourceId = ''; state.facts = []; state.factSignature = null; state.previewSequence++;
  clearTimeout(state.timer);
  state.sequence++;
  state.caseId = id;
  state.imageId = null;
  state.answerId = null;
  state.images = [];
  state.runs = [];
  state.reports = [];
  state.reportSignature = null;
  const url = new URL(location.href);
  url.searchParams.set('case', id);
  history.replaceState(null, '', url);
  const item = state.cases.find(entry => entry.id === id);
  $('case-heading').textContent = item?.title || '檢驗工作台';
  $('case-description').textContent = `案件 ${short(id)}，圖片、來源與執行紀錄會保存在這裡。`;
  $('welcome').hidden = true;
  $('case-workspace').hidden = false;
  notice('');
  renderCases();
  render();
  await refreshCase();
}
async function refreshCase() {
  if (!state.caseId) return;
  const caseId = state.caseId;
  const sequence = ++state.sequence;
  try {
    const [images, runs, reports, facts] = await Promise.all([
      api(`${base(caseId)}/images`), api(`${base(caseId)}/runs`), api(`${base(caseId)}/reports`), api(`${base(caseId)}/facts`)]);
    if (caseId !== state.caseId || sequence !== state.sequence) return;
    state.images = images.items;
    state.runs = runs.items;
    state.reports = reports.items;
    state.facts = facts.items;
    if (!state.images.some(image => image.id === state.imageId)) state.imageId = state.images.at(-1)?.id || null;
    if (!state.runs.some(run => run.id === state.answerId)) state.answerId = [...state.runs].reverse().find(run => run.kind === 'agent')?.id || null;
    render();
    await refreshMemoryPreview();
  } catch (error) { if (caseId === state.caseId && sequence === state.sequence) showError(error); }
  finally { if (caseId === state.caseId && sequence === state.sequence) schedulePoll(); }
}
function schedulePoll() {
  clearTimeout(state.timer);
  if (state.runs.some(run => ['pending', 'running'].includes(run.status)) && !document.hidden) {
    state.timer = setTimeout(refreshCase, 1500);
  }
}
function setImage(node, url, placeholder) {
  node.hidden = !url;
  if (url) { if (node.getAttribute('src') !== url) node.src = url; }
  else node.removeAttribute('src');
  if (placeholder) placeholder.hidden = Boolean(url);
}
function renderImages() {
  $('image-count').textContent = `${state.images.length} 張圖片`;
  $('image-strip').replaceChildren();
  for (const image of state.images) {
    const button = el('button', 'thumbnail');
    button.type = 'button';
    button.title = `圖片 ${short(image.id)}`;
    button.setAttribute('aria-label', `選取圖片 ${short(image.id)}`);
    button.setAttribute('aria-pressed', String(image.id === state.imageId));
    const thumbnail = el('img'); thumbnail.src = imageUrl(image); thumbnail.alt = '';
    button.append(thumbnail);
    button.addEventListener('click', () => { state.imageId = image.id; state.memorySourceId = ''; renderImages(); renderReferences(); renderMemory(); refreshMemoryPreview(); updateButtons(); });
    $('image-strip').append(button);
  }
  const image = state.images.find(item => item.id === state.imageId);
  setImage($('original-image'), image && imageUrl(image), $('original-empty'));
  $('image-size').textContent = image ? `${image.width} × ${image.height}` : '';
  const run = latestForImage(state.runs, state.imageId, 'analysis');
  const result = analysisOf(run);
  setImage($('heatmap-image'), result ? `${runBase(run)}/heatmap` : null, $('heatmap-empty'));
  $('heatmap-state').textContent = result ? `執行 ${short(run.id)}` : '等待分析';
  $('score').textContent = Number.isFinite(result?.score) ? result.score.toFixed(2) : '待分析';
  $('threshold').textContent = Number.isFinite(result?.threshold) ? result.threshold.toFixed(2) : '待分析';
  $('verdict').textContent = result ? (result.is_anomalous ? '外觀異常，需複查' : '未超過判斷門檻') : '尚未分析';
  $('verdict').className = `verdict ${result ? (result.is_anomalous ? 'abnormal' : 'normal') : ''}`;
}
function renderReferences() {
  const run = latestReferences(state.runs, state.imageId);
  const matches = referencesOf(run);
  $('reference-count').textContent = matches.length ? `${matches.length} 張參考圖` : '尚未搜尋';
  $('reference-list').replaceChildren();
  if (!matches.length) $('reference-list').append(el('p', 'empty-text', '按「找正常參考圖」，搜尋外觀相近的正常訓練圖片。'));
  matches.forEach((item, index) => {
    const figure = el('figure', 'reference');
    const image = el('img'); image.src = `${runBase(run)}/references/${index}`;
    image.alt = `第 ${index + 1} 張正常參考圖片，${item.path}`; image.loading = 'lazy';
    const caption = el('figcaption', '', item.path);
    caption.append(el('strong', '', `相似度 ${Number(item.cosine_similarity).toFixed(4)}`));
    figure.append(image, caption); $('reference-list').append(figure);
  });
}
function renderCitations(target, citations) {
  target.replaceChildren();
  for (const citation of citations || []) {
    const node = el('div', 'citation');
    const url = safeSourceUrl(citation.source_url);
    if (url) {
      const link = el('a', '', `${citation.title || citation.id} ↗`);
      link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; node.append(link);
    } else node.append(el('span', '', citation.title || citation.id));
    if (citation.kind === 'case_memory') {
      const details = el('details'); details.append(el('summary', '', citation.memory_type === 'user_observation' ? '使用者觀察，未經獨立驗證' : '歷史工具結果，未重新計算'));
      if (citation.text) details.append(el('p', '', citation.text));
      if (Number.isFinite(citation.score)) details.append(el('p', '', `分數 ${citation.score}，門檻 ${citation.threshold}`));
      if (citation.checkpoint_sha256) details.append(el('small', '', `模型雜湊 ${citation.checkpoint_sha256}`));
      node.append(details);
    }
    node.append(el('small', '', `${citation.id}${citation.source_locator ? ' · ' + citation.source_locator : ''}`));
    target.append(node);
  }
}
function showAnswer(target, result, question) {
  target.replaceChildren();
  if (question) target.append(el('p', 'question-label', question));
  if (!result?.answer) { target.append(el('p', 'empty-text', '回答尚未產生，請查看執行紀錄與狀態。')); return; }
  if (result.case_memory?.enabled) target.append(el('p', 'memory-result-note', result.case_memory.read
    ? `本輪已讀取案件記憶，快照 ${short(result.case_memory.snapshot_sha256)}，來源執行 ${short(result.case_memory.anchor_run_id) || '尚無圖片分析'}。`
    : '本輪提供案件記憶，引用情況請查看工具流程。'));
  if (hasRetractedObservation(result, state.facts)) target.append(el('p', 'memory-result-note', '這份歷史回答引用的觀察已撤回，請完成新的問答後再建立或確認報告。'));
  const answer = result.answer;
  if (answer.status !== 'answered') target.append(el('p', 'answer-status', answer.status === 'needs_context' ? '需要補充資訊，再依來源確認。' : '現有證據不足，請檢查限制說明。'));
  (answer.claims || []).forEach((claim, index) => {
    const node = el('p', 'claim');
    node.append(el('span', 'claim-index', index + 1), document.createTextNode(claim.text), el('br'), el('small', '', claim.evidence_ids.join(' · ')));
    target.append(node);
  });
  if (answer.limitations?.length) {
    const details = el('details');
    details.append(el('summary', '', '限制與需要確認的事項'));
    const list = el('ul'); answer.limitations.forEach(text => list.append(el('li', '', text)));
    details.append(list); target.append(details);
  }
  if (answer.follow_up_question) target.append(el('p', '', answer.follow_up_question));
  target.append(el('small', '', '引用編號已由程式檢查，內容是否獲得支持仍需核對來源。'));
  const trace = el('details');
  trace.append(el('summary', '', `工具流程（Tool Trace） · ${result.tool_calls ?? 0} 次工具呼叫`));
  const list = el('ol');
  (result.tool_trace || []).forEach(item => list.append(el('li', '', `${item.tool} · ${item.status}`)));
  trace.append(list); target.append(trace);
}
function renderAnswer() {
  const runs = [...state.runs].reverse().filter(run => run.kind === 'agent');
  const select = $('answer-select'); select.replaceChildren();
  if (!runs.length) select.append(new Option('尚無問答', ''));
  for (const run of runs) select.append(new Option(`${dateText(run.created_at)} · ${short(run.id)} · ${statuses[run.status]}`, run.id));
  select.value = state.answerId || '';
  const run = runs.find(item => item.id === state.answerId);
  if (!run) {
    $('answer').replaceChildren(el('p', 'empty-text', '送出問題後，這裡會顯示回答、引用與限制。'));
    $('citation-list').replaceChildren(); return;
  }
  showAnswer($('answer'), run.result, run.question);
  renderCitations($('citation-list'), run.result?.citations);
}
function renderRuns() {
  $('run-count').textContent = `${state.runs.length} 筆`;
  $('run-list').replaceChildren();
  if (!state.runs.length) $('run-list').append(el('li', 'empty-text', '分析與問答的狀態，會保存在這裡。'));
  for (const run of [...state.runs].reverse()) {
    const item = el('li', 'run-item');
    item.append(el('span', `run-indicator ${run.status}`));
    const copy = el('div', 'run-copy');
    copy.append(el('strong', '', kinds[run.kind] || run.kind), el('small', '', `${dateText(run.created_at)} · ${short(run.id)}${run.image_id ? ' · 圖片 ' + short(run.image_id) : ''}`));
    if (run.error) copy.append(el('span', 'run-error', errorText(run.error)));
    item.append(copy, el('span', 'run-status', statuses[run.status] || run.status));
    $('run-list').append(item);
  }
}
function renderReports() {
  const signature = JSON.stringify([state.reports, state.facts.map(fact => [fact.id, fact.retracted_at])]);
  if (signature === state.reportSignature) return;
  state.reportSignature = signature;
  $('report-count').textContent = `${state.reports.length} 個版本`;
  $('report-list').replaceChildren();
  if (!state.reports.length) $('report-list').append(el('p', 'empty-text', '完成一次有來源的問答，再儲存成報告草稿，來源與回答會一起留下。'));
  for (const report of [...state.reports].reverse()) {
    const details = el('details', 'report');
    const summary = el('summary');
    summary.append(el('strong', '', `報告 v${report.version}`), el('span', 'muted', dateText(report.created_at)), el('span', 'tag', report.confirmed_at ? '已確認' : '待審閱'));
    details.append(summary);
    const body = el('div', 'report-content'); showAnswer(body, report.snapshot);
    const citations = el('div'); renderCitations(citations, report.snapshot.citations);
    details.append(body, citations);
    const actions = el('div', 'report-actions');
    if (!report.confirmed_at) {
      const label = el('label', 'checkbox-label');
      const checkbox = el('input'); checkbox.type = 'checkbox';
      label.append(checkbox, document.createTextNode('我已核對內容與引用來源'));
      const confirm = el('button', 'button primary', '確認這個版本');
      confirm.type = 'button'; confirm.disabled = true;
      checkbox.addEventListener('change', () => { confirm.disabled = !checkbox.checked || hasRetractedObservation(report.snapshot, state.facts); });
      confirm.addEventListener('click', () => action(async () => {
        if (!checkbox.checked) return;
        confirm.disabled = true;
        try {
          await post(`${base(report.case_id)}/reports/${report.id}/confirm`, {accepted: true});
          if (state.caseId === report.case_id) { await refreshCase(); notice(`報告 v${report.version} 已確認，確認時間已保存。`, true); }
        } finally { if (confirm.isConnected) confirm.disabled = !checkbox.checked; }
      }));
      actions.append(label, confirm);
    } else actions.append(el('span', 'muted', `確認時間：${dateText(report.confirmed_at)}`));
    const download = el('button', 'button secondary', '下載紀錄（JSON）'); download.type = 'button';
    download.addEventListener('click', () => {
      const objectUrl = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type: 'application/json'}));
      const link = el('a'); link.href = objectUrl; link.download = `InspectRAG-report-v${report.version}.json`; link.click();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    });
    actions.append(download); details.append(actions); $('report-list').append(details);
  }
}
function render() { renderImages(); renderReferences(); renderAnswer(); renderRuns(); renderReports(); renderMemory(); updateButtons(); }
async function upload(file) {
  if (!file || !state.caseId) return;
  if (file.size > 10 * 1024 * 1024) throw new Error('image_too_large');
  const caseId = state.caseId;
  const form = new FormData(); form.append('file', file, file.name || 'sample.png');
  const image = await api(`${base(caseId)}/images`, {method: 'POST', body: form});
  if (caseId !== state.caseId) return;
  state.imageId = image.id;
  await refreshCase(); notice('圖片已保存，接著可以分析外觀或搜尋正常參考圖。', true);
}
async function submitRun(kind, question = '') {
  const caseId = state.caseId;
  const imageId = kind === 'agent' && !$('include-image').checked ? null : state.imageId;
  const body = {kind, question, image_id: imageId};
  if (kind === 'agent') {
    body.use_case_memory = $('use-memory').checked;
    body.memory_image_id = body.use_case_memory ? state.imageId : null;
    body.context_run_id = body.use_case_memory ? memoryAnchor(state.runs, state.imageId, state.memorySourceId) : null;
  }
  const signature = JSON.stringify([caseId, body]);
  const requestKey = retryKeys.get(signature) || crypto.randomUUID().replaceAll('-', '');
  retryKeys.set(signature, requestKey);
  const run = await post(`${base(caseId)}/runs`, {...body, request_key: requestKey});
  retryKeys.delete(signature);
  if (caseId !== state.caseId) return;
  if (kind === 'agent') state.answerId = run.id;
  await refreshCase(); notice('工作已送出，執行狀態會在紀錄中更新。', true);
}
function renderMemory() {
  const select = $('memory-source'); select.replaceChildren();
  select.append(new Option('目前圖片最近完成的執行', ''));
  const eligible = state.runs.filter(run => run.status === 'succeeded' && (!state.imageId || run.image_id === state.imageId));
  for (const run of [...eligible].reverse()) select.append(new Option(`${kinds[run.kind]} · ${short(run.id)} · ${dateText(run.created_at)}`, run.id));
  if (!eligible.some(run => run.id === state.memorySourceId)) state.memorySourceId = '';
  select.value = state.memorySourceId;
  const active = state.facts.filter(fact => !fact.retracted_at);
  $('fact-count').textContent = `${active.length} 筆有效觀察`;
  const signature = JSON.stringify([state.imageId, state.facts]);
  if (signature === state.factSignature) return;
  state.factSignature = signature;
  $('fact-list').replaceChildren();
  if (!state.facts.length) $('fact-list').append(el('p', 'empty-text', '尚無觀察，模型推測不會加入這份紀錄。'));
  for (const fact of [...state.facts].reverse()) {
    const row = el('div', `fact ${fact.retracted_at ? 'retracted' : ''}`);
    row.append(el('p', '', fact.text), el('small', '', `${fact.image_id ? '圖片 ' + short(fact.image_id) : '案件共用'} · ${dateText(fact.confirmed_at)} · ${fact.retracted_at ? '已撤回' : '使用者確認'}`));
    if (!fact.retracted_at) {
      const button = el('button', 'button subtle', '撤回觀察'); button.type = 'button';
      button.addEventListener('click', () => action(async () => {
        await post(`${base(fact.case_id)}/facts/${fact.id}/retract`, {accepted: true});
        if (state.caseId === fact.case_id) { await refreshCase(); notice('觀察已撤回，新建立的記憶快照會排除這筆資料。', true); }
      })); row.append(button);
    }
    $('fact-list').append(row);
  }
}
async function refreshMemoryPreview() {
  const sequence = ++state.previewSequence;
  const caseId = state.caseId;
  if (!$('use-memory').checked || !caseId) { $('memory-preview').textContent = '本輪不帶入案件記憶，仍可查詢文件或分析勾選的圖片。'; return; }
  const anchor = memoryAnchor(state.runs, state.imageId, state.memorySourceId);
  const params = new URLSearchParams();
  if (state.imageId) params.set('image_id', state.imageId);
  if (anchor) params.set('context_run_id', anchor);
  try {
    const snapshot = await api(`${base(caseId)}/memory-preview?${params}`);
    if (caseId !== state.caseId || sequence !== state.previewSequence) return;
    $('memory-preview').textContent = snapshot.status === 'needs_anchor'
      ? '案件有多張圖片，請選擇圖片或追問來源，再引用歷史分析。'
      : `可帶入 ${snapshot.evidence.length} 項證據，來源執行 ${short(snapshot.anchor_run_id) || '尚無'}，圖片 ${short(snapshot.scope_image_id) || '案件共用'}${snapshot.omitted_facts ? '，另有 ' + snapshot.omitted_facts + ' 筆觀察未納入字數預算' : ''}。`;
  } catch (error) { if (caseId === state.caseId && sequence === state.previewSequence) $('memory-preview').textContent = errorText(error.message); }
}
$('use-memory').addEventListener('change', () => { updateButtons(); refreshMemoryPreview(); });
$('memory-source').addEventListener('change', event => { state.memorySourceId = event.target.value; refreshMemoryPreview(); });
$('fact-confirm').addEventListener('change', updateButtons);
$('fact-image-scope').addEventListener('change', updateButtons);
$('fact-form').addEventListener('submit', event => {
  event.preventDefault();
  action(async () => {
    const text = $('fact-text').value.trim();
    if (!text || !$('fact-confirm').checked) return;
    const caseId = state.caseId;
    await post(`${base(caseId)}/facts`, {text, image_id: $('fact-image-scope').checked ? state.imageId : null, accepted: true});
    if (state.caseId === caseId) { $('fact-text').value = ''; $('fact-confirm').checked = false; await refreshCase(); notice('觀察已保存，帶入記憶時會標示為使用者提供的資料。', true); }
  });
});
$('new-case-form').addEventListener('submit', event => {
  event.preventDefault();
  action(async () => {
    const title = $('case-title').value.trim();
    if (!title) return;
    const item = await post('/cases', {title});
    $('case-title').value = ''; await loadCases(item.id);
  });
});
$('focus-new-case').addEventListener('click', () => $('case-title').focus());
$('refresh').addEventListener('click', () => action(async () => { await api('/health'); await loadCases(); notice('案件紀錄已更新，可以繼續操作。', true); }));
$('upload-input').addEventListener('change', event => {
  const file = event.target.files[0];
  action(async () => { try { await upload(file); } finally { event.target.value = ''; } });
});
$('load-sample').addEventListener('click', () => action(async () => {
  let response;
  try { response = await fetch('/demo/bottle.png'); }
  catch { throw new Error('network_error'); }
  if (!response.ok) throw new Error('sample_data_not_installed');
  const blob = await response.blob(); await upload(new File([blob], 'bottle-example.png', {type: 'image/png'}));
}));
$('analyze').addEventListener('click', () => action(() => submitRun('analysis')));
$('find-references').addEventListener('click', () => action(() => submitRun('references')));
$('question-form').addEventListener('submit', event => {
  event.preventDefault();
  const question = $('question').value.trim();
  if (!question) { $('question').focus(); return; }
  action(() => submitRun('agent', question));
});
for (const button of document.querySelectorAll('[data-question]')) button.addEventListener('click', () => { $('question').value = button.dataset.question; $('question').focus(); });
$('answer-select').addEventListener('change', event => { state.answerId = event.target.value; renderAnswer(); updateButtons(); });
$('draft-report').addEventListener('click', () => action(async () => {
  const run = state.runs.find(item => item.id === state.answerId);
  if (!canDraft(run)) return;
  await post(`${base(run.case_id)}/reports`, {run_id: run.id});
  if (state.caseId === run.case_id) { await refreshCase(); notice('報告草稿已保存，請核對內容與引用，再確認這個版本。', true); }
}));
for (const id of ['original-image', 'heatmap-image']) $(id).addEventListener('error', () => {
  $(id).hidden = true;
  const placeholder = id === 'original-image' ? $('original-empty') : $('heatmap-empty');
  placeholder.hidden = false;
  placeholder.textContent = '圖片讀取未完成，請重新整理案件紀錄。';
});
document.addEventListener('visibilitychange', () => { if (document.hidden) clearTimeout(state.timer); else refreshCase(); });
window.addEventListener('pagehide', () => clearTimeout(state.timer));
updateButtons();
api('/health').then(() => loadCases()).catch(showError);
