// Pure presentation helpers, shared by the browser and Node's built-in tests.
export function safeSourceUrl(value) {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
export function latestForImage(runs, imageId, kind) {
  if (!imageId) return undefined;
  return [...runs].reverse().find(run => run.image_id === imageId && run.status === 'succeeded' &&
    (run.kind === kind || (kind === 'analysis' && run.kind === 'agent' &&
      (run.result?.citations || []).some(item => item.kind === 'analysis'))));
}
export function analysisOf(run) {
  if (!run) return null;
  if (run.kind === 'analysis') return run.result;
  return (run.result?.citations || []).find(item => item.kind === 'analysis') || null;
}
export function referencesOf(run) {
  if (!run) return [];
  const result = run.result || {};
  const evidence = [...Object.values(result.evidence || {}), ...(result.citations || [])];
  return evidence.find(item => item.kind === 'image_references')?.matches?.slice(0, 3) || [];
}
export function latestReferences(runs, imageId) {
  if (!imageId) return undefined;
  return [...runs].reverse().find(run => run.image_id === imageId && run.status === 'succeeded' && referencesOf(run).length);
}
export function canDraft(run) {
  return Boolean(run?.status === 'succeeded' && run.kind === 'agent' && run.result?.status === 'answered' && run.result?.answer);
}
export const statuses = {pending: '等待執行', running: '執行中', succeeded: '已完成', failed: '執行失敗'};
export const kinds = {analysis: '圖片分析', references: '正常參考圖搜尋', agent: '來源問答'};
export const errorLabels = {
  rate_limited: 'Groq 免費額度不足，請等額度恢復後再提出新工作。',
  credential_not_configured: 'Groq 金鑰尚未設定，請檢查本機設定。',
  authentication_failed: 'Groq 金鑰驗證失敗，請檢查本機設定。',
  local_queue_full: '目前已有四筆工作執行或等候，請等工作完成後再送出。',
  idempotency_conflict: '這個請求編號已有其他內容，請重新整理案件紀錄。',
  execution_failed: '執行未完成，請檢查本機模型與索引是否已建立。',
  server_restarted: '服務曾中斷，這筆工作沒有自動重新執行。',
  references_requires_image: '請選擇圖片，再搜尋正常參考圖。',
  image_too_large: '圖片超過 10 MiB，請縮小檔案後再上傳。',
  image_dimensions_too_large: '圖片超過 1,600 萬像素，請縮小尺寸後再上傳。',
  invalid_image: '圖片無法解碼，請選擇可讀取的 PNG 或 JPEG。',
  png_or_jpeg_required: '圖片格式不支援，請使用 PNG 或 JPEG。',
  sample_data_not_installed: '本機尚未安裝範例資料，請依資料階段文件準備 bottle 資料夾。',
  reference_source_changed: '參考圖與保存的雜湊不符，請重新驗證資料來源。'
};
export function errorText(code) { return errorLabels[code] || '操作未完成，請重新整理後查看案件紀錄。'; }
export function samePending(runs, kind, imageId) {
  return runs.some(run => run.kind === kind && run.image_id === imageId && ['pending', 'running'].includes(run.status));
}
