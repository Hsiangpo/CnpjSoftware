const state = {
  jobId: null,
  pollTimer: null,
  pollInFlight: false,
  lastResults: [],
  lastJob: null,
  currentPage: 1,
  pageSize: 10,
  followLatestPage: true,
  apiKeyMasked: false,
  apiKeyDirty: false,
  proxyPasswordMasked: false,
  proxyPasswordDirty: false,
  sourceFiles: [],
  selectedSourceName: "",
  sourceQueue: [],
  outputFiles: [],
  resultFilter: "all",
  settings: null,
  health: null,
  queueRunning: false,
  submitting: false,
};

const ACTIVE_JOB_STATUSES = new Set(["queued", "running", "canceling"]);
const TERMINAL_JOB_STATUSES = new Set(["completed", "failed", "canceled"]);
const MAX_FAILED_RETRY_ROUNDS = 3;

const els = {
  apiBadge: document.getElementById("apiBadge"),
  apiKeyInput: document.getElementById("apiKeyInput"),
  modelInput: document.getElementById("modelInput"),
  proxyHostInput: document.getElementById("proxyHostInput"),
  proxyRegionInput: document.getElementById("proxyRegionInput"),
  proxyUsernameInput: document.getElementById("proxyUsernameInput"),
  proxyPasswordInput: document.getElementById("proxyPasswordInput"),
  proxyProtocolInput: document.getElementById("proxyProtocolInput"),
  proxySessionInput: document.getElementById("proxySessionInput"),
  concurrencyInput: document.getElementById("concurrencyInput"),
  blurpathPortsInput: document.getElementById("blurpathPortsInput"),
  blurpathPortsHint: document.getElementById("blurpathPortsHint"),
  saveSettingsButton: document.getElementById("saveSettingsButton"),
  settingsStatus: document.getElementById("settingsStatus"),
  proxyPreflightButton: document.getElementById("proxyPreflightButton"),
  blurpathStatus: document.getElementById("blurpathStatus"),
  proxyProbeList: document.getElementById("proxyProbeList"),
  sourceFileSelect: document.getElementById("sourceFileSelect"),
  queueSourceButton: document.getElementById("queueSourceButton"),
  sourceDirHint: document.getElementById("sourceDirHint"),
  sourceMeta: document.getElementById("sourceMeta"),
  outputHint: document.getElementById("outputHint"),
  sourceFileName: document.getElementById("sourceFileName"),
  sourceRows: document.getElementById("sourceRows"),
  sourceUnique: document.getElementById("sourceUnique"),
  sourceResume: document.getElementById("sourceResume"),
  sourceOutputName: document.getElementById("sourceOutputName"),
  sourceOutputTime: document.getElementById("sourceOutputTime"),
  queueList: document.getElementById("queueList"),
  guardFile: document.getElementById("guardFile"),
  guardUnique: document.getElementById("guardUnique"),
  guardConcurrency: document.getElementById("guardConcurrency"),
  guardProviders: document.getElementById("guardProviders"),
  guardPorts: document.getElementById("guardPorts"),
  openOutputDirButton: document.getElementById("openOutputDirButton"),
  outputList: document.getElementById("outputList"),
  startButton: document.getElementById("startButton"),
  stopButton: document.getElementById("stopButton"),
  clearButton: document.getElementById("clearButton"),
  inputCount: document.getElementById("inputCount"),
  doneCount: document.getElementById("doneCount"),
  normalCount: document.getElementById("normalCount"),
  issueCount: document.getElementById("issueCount"),
  jobStatus: document.getElementById("jobStatus"),
  progressBar: document.getElementById("progressBar"),
  resultBody: document.getElementById("resultBody"),
  prevPageButton: document.getElementById("prevPageButton"),
  nextPageButton: document.getElementById("nextPageButton"),
  pageInfo: document.getElementById("pageInfo"),
  runtimeProvider: document.getElementById("runtimeProvider"),
  runtimePort: document.getElementById("runtimePort"),
  runtimeSuccessRate: document.getElementById("runtimeSuccessRate"),
  runtimeEta: document.getElementById("runtimeEta"),
  failureFilterAll: document.getElementById("failureFilterAll"),
  failureFilterIssues: document.getElementById("failureFilterIssues"),
  failureFilterPartial: document.getElementById("failureFilterPartial"),
  failureFilterSuccess: document.getElementById("failureFilterSuccess"),
  copyFailedButton: document.getElementById("copyFailedButton"),
  runFailedButton: document.getElementById("runFailedButton"),
};

function isJobActive(job = state.lastJob) {
  return Boolean(job && ACTIVE_JOB_STATUSES.has(job.status));
}

function isJobTerminal(job = state.lastJob) {
  return Boolean(job && TERMINAL_JOB_STATUSES.has(job.status));
}

function isRunActive() {
  return state.submitting || state.queueRunning || isJobActive();
}

function normalizeCnpjKey(value) {
  return String(value || "").replace(/\D+/g, "");
}

function uniqueItemsByCnpj(items) {
  const map = new Map();
  (Array.isArray(items) ? items : []).forEach((item, index) => {
    const rawKey = item?.normalized_cnpj || item?.input_cnpj || String(index);
    const key = normalizeCnpjKey(rawKey) || rawKey || String(index);
    map.set(key, item);
  });
  return Array.from(map.values());
}

function uniqueInputCount(items) {
  const keys = new Set(
    (Array.isArray(items) ? items : [])
      .map((item) => normalizeCnpjKey(item) || String(item || ""))
      .filter(Boolean)
  );
  return keys.size;
}

function hasResponsibleName(item) {
  const names = item?.responsible?.names;
  return Array.isArray(names) && names.some((name) => String(name || "").trim());
}

function isBusinessSuccess(item) {
  if (!item) return false;
  if (item.status === "success") return true;
  return item.status === "partial_success"
    && item?.responsible?.analysis_source === "rule_fallback"
    && hasResponsibleName(item);
}

function hardFailedResults(results = state.lastResults) {
  return uniqueItemsByCnpj(results).filter((item) => !isBusinessSuccess(item) && item.status !== "partial_success");
}

function abnormalResults(results = state.lastResults) {
  return uniqueItemsByCnpj(results).filter((item) => !isBusinessSuccess(item));
}

function queuedSources() {
  return state.sourceQueue.filter((item) => item.status === "queued");
}

function queueItemLabel(item) {
  return item?.displayName || item?.name || "-";
}

function queueItemKey(item) {
  if (!item) return "";
  if (item.kind === "retry_failed") {
    return `${item.kind}:${item.parentJobId}:${item.retryAttempt}`;
  }
  return `${item.kind || "source"}:${item.name || ""}`;
}

function hasQueueItem(item) {
  const key = queueItemKey(item);
  return Boolean(key) && state.sourceQueue.some((existing) => {
    if (existing.status === "completed" || existing.status === "canceled" || existing.status === "failed") {
      return false;
    }
    return queueItemKey(existing) === key;
  });
}

function appendQueueItem(item) {
  if (!item || hasQueueItem(item)) {
    return false;
  }
  state.sourceQueue.push(item);
  return true;
}

function activeQueueItem() {
  if (!state.sourceQueue.length) return null;
  return state.sourceQueue.find((item) => item.jobId && item.jobId === state.jobId)
    || state.sourceQueue.find((item) => item.status === "running")
    || null;
}

function clearPollTimer() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

function syncRunButtons() {
  const active = isRunActive();
  const hasQueued = queuedSources().length > 0;
  const nameMode = state.lastJob?.mode === "name";
  els.startButton.disabled = active || (!hasQueued && !state.selectedSourceName);
  els.stopButton.disabled = !state.jobId || !isJobActive() || state.lastJob?.status === "canceling";
  els.clearButton.disabled = active;
  els.queueSourceButton.disabled = active || !state.selectedSourceName;
  els.copyFailedButton.disabled = nameMode || !hardFailedResults().length;
  els.runFailedButton.disabled = active || !state.jobId || !isJobTerminal() || !abnormalResults().length;
}

function renderMetrics(job = state.lastJob) {
  if (job && job.mode === "name") {
    const results = Array.isArray(job.results) ? job.results : [];
    const total = Number(job.total_units || results.length);
    const completed = results.length;
    const normal = results.filter((item) => isBusinessSuccess(item)).length;
    els.inputCount.textContent = String(Math.max(0, total - completed));
    els.doneCount.textContent = String(completed);
    els.normalCount.textContent = String(normal);
    els.issueCount.textContent = String(completed - normal);
    return;
  }
  if (job && Array.isArray(job.input_cnpjs)) {
    const results = Array.isArray(job.results) ? job.results : [];
    const uniqueResults = uniqueItemsByCnpj(results);
    const completed = uniqueResults.length;
    const pending = Math.max(0, uniqueInputCount(job.input_cnpjs) - completed);
    const normal = uniqueResults.filter((item) => isBusinessSuccess(item)).length;
    const abnormal = completed - normal;
    els.inputCount.textContent = String(pending);
    els.doneCount.textContent = String(completed);
    els.normalCount.textContent = String(normal);
    els.issueCount.textContent = String(abnormal);
    return;
  }

  const selected = selectedSource();
  const total = Number(selected?.unique_count || selected?.count || 0);
  const normal = Number(selected?.normal_count || 0);
  const abnormal = Number(selected?.abnormal_count || 0);
  const completed = normal + abnormal;
  const pending = Math.max(0, total - completed);
  els.inputCount.textContent = String(pending);
  els.doneCount.textContent = String(completed);
  els.normalCount.textContent = String(normal);
  els.issueCount.textContent = String(abnormal);
}

function statusLabel(status) {
  const labels = {
    queued: "排队",
    running: "处理中",
    canceling: "停止中",
    canceled: "已停止",
    completed: "完成",
    failed: "失败",
    success: "成功",
    partial_success: "部分成功",
    blocked_by_cloudflare: "Cloudflare拦截",
    fetch_error: "采集失败",
    not_found: "未找到",
  };
  return labels[status] || status || "-";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDateTime(timestamp) {
  if (!timestamp) return "-";
  return new Date(timestamp * 1000).toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatEtaSeconds(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "-";
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  return `${minutes}m ${String(secs).padStart(2, "0")}s`;
}

function renderProxyProbeResults(results) {
  const rows = Array.isArray(results) ? results : [];
  if (!rows.length) {
    els.proxyProbeList.innerHTML = "";
    return;
  }
  els.proxyProbeList.innerHTML = rows.map((item) => {
    const ok = Boolean(item.ok);
    const detail = ok ? (item.ip || "OK") : (item.error || `HTTP ${item.status_code || "-"}`);
    return `
      <div class="probe-row ${ok ? "ok" : "warn"}">
        <span class="probe-port">${escapeHtml(item.port || "-")}</span>
        <span class="probe-status">${ok ? "OK" : "失败"}</span>
        <span class="probe-detail" title="${escapeHtml(detail)}">${escapeHtml(detail)}</span>
      </div>
    `;
  }).join("");
}

function syncApiKeyField(value) {
  const masked = value === "<set>";
  state.apiKeyMasked = masked;
  state.apiKeyDirty = false;
  els.apiKeyInput.value = "";
  els.apiKeyInput.placeholder = masked ? "已设置，留空保持不变" : "未设置";
}

function syncProxyPasswordField(value) {
  const masked = value === "<set>";
  state.proxyPasswordMasked = masked;
  state.proxyPasswordDirty = false;
  els.proxyPasswordInput.value = "";
  els.proxyPasswordInput.placeholder = masked ? "已设置，留空保持不变" : "未设置";
}

function renderPagination(pageCount) {
  if (!pageCount) {
    els.pageInfo.textContent = "第 0 / 0 页";
    els.prevPageButton.disabled = true;
    els.nextPageButton.disabled = true;
    return;
  }
  els.pageInfo.textContent = `第 ${state.currentPage} / ${pageCount} 页 · 每页 ${state.pageSize} 条`;
  els.prevPageButton.disabled = state.currentPage <= 1;
  els.nextPageButton.disabled = state.currentPage >= pageCount;
}

function updateOutputHint(path) {
  if(els.outputHint) els.outputHint.textContent = `输出文件：${path || "-"}`;
}

function selectedSource() {
  return state.sourceFiles.find((item) => item.name === state.selectedSourceName) || null;
}

function renderOutputFiles() {
  if (!state.outputFiles.length) {
    els.outputList.innerHTML = '<div class="empty-state-dark">output 目录暂无产物</div>';
    return;
  }
  els.outputList.innerHTML = state.outputFiles.slice(0, 6).map((item) => `
    <div class="artifact-item">
      <div class="artifact-info">
        <div class="artifact-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
        <div class="artifact-meta">${escapeHtml(formatBytes(item.size_bytes))} · ${escapeHtml(formatDateTime(item.modified_at))}</div>
      </div>
      <button class="btn btn-secondary-dark btn-xs open-output-file-button" data-filename="${escapeHtml(item.name)}" type="button">打开</button>
    </div>
  `).join("");
  els.outputList.querySelectorAll(".open-output-file-button").forEach((button) => {
    button.addEventListener("click", () => openOutputFile(button.dataset.filename || ""));
  });
}

function buildFailedRetryQueueItem(job, retryAttempt) {
  const attempt = Number(retryAttempt || 0);
  if (!job || job.status !== "completed" || attempt < 1 || attempt > MAX_FAILED_RETRY_ROUNDS) {
    return null;
  }
  // Failed-retry is CNPJ-keyed; name-mode "not found" rows can't be retried that way.
  if (job.mode === "name") {
    return null;
  }
  const abnormal = abnormalResults(job.results || []);
  if (!abnormal.length) {
    return null;
  }
  const sourceName = job.source_name || job.filename || job.job_id || "任务";
  const stem = sourceName.replace(/\.[^.]+$/, "") || sourceName;
  return {
    kind: "retry_failed",
    name: sourceName,
    displayName: `${stem} · 失败重跑 ${attempt}/${MAX_FAILED_RETRY_ROUNDS}`,
    status: "queued",
    jobId: "",
    parentJobId: job.job_id,
    retryAttempt: attempt,
  };
}

function sourceQueueItem(name) {
  return {
    kind: "source",
    name,
    displayName: name,
    status: "queued",
    jobId: "",
    parentJobId: "",
    retryAttempt: 0,
  };
}

function renderQueue() {
  if (!state.sourceQueue.length) {
    els.queueList.innerHTML = '<div class="empty-state">当前队列为空</div>';
    syncRunButtons();
    return;
  }
  els.queueList.innerHTML = state.sourceQueue.map((item, index) => {
    let statusClass = "status-neutral";
    if(item.status === "running") statusClass = "status-active";
    if(item.status === "completed") statusClass = "status-success";
    if(item.status === "failed" || item.status === "canceled") statusClass = "status-danger";
    const removeDisabled = isRunActive() ? "disabled" : "";
    
    return `
      <div class="queue-item">
        <div class="queue-info">
          <div class="queue-name" title="${escapeHtml(queueItemLabel(item))}">${escapeHtml(queueItemLabel(item))}</div>
          <div class="status-badge ${statusClass}">${escapeHtml(statusLabel(item.status || "queued"))}</div>
        </div>
        <button class="btn btn-secondary btn-xs remove-queue-button" data-index="${index}" type="button" ${removeDisabled}>移除</button>
      </div>
    `;
  }).join("");
  els.queueList.querySelectorAll(".remove-queue-button").forEach((button) => {
    button.addEventListener("click", () => removeFromQueue(Number(button.dataset.index)));
  });
  syncRunButtons();
}

function renderSourceSummary() {
  const selected = selectedSource();
  if (!selected) {
    if(els.sourceMeta) els.sourceMeta.textContent = "请选择文件";
    updateOutputHint("-");
    els.sourceFileName.textContent = "-";
    els.sourceRows.textContent = "0";
    els.sourceUnique.textContent = "0";
    els.sourceResume.textContent = "0/0";
    els.sourceOutputName.textContent = "-";
    els.sourceOutputTime.textContent = "-";
    renderMetrics(null);
    renderGuard();
    syncRunButtons();
    return;
  }
  const resume = selected.resume || {};
  const total = Number(resume.total_count || selected.unique_count || 0);
  const done = Number(resume.done_count || 0);
  const ratio = total ? `${Math.round((done / total) * 100)}%` : "0%";
  if(els.sourceMeta) els.sourceMeta.textContent = `${selected.source_type.toUpperCase()} · ${formatBytes(selected.size_bytes)} · 已完成 ${done}/${total || selected.unique_count || 0}`;
  updateOutputHint(selected.output_name || "-");
  els.sourceFileName.textContent = selected.name || "-";
  els.sourceRows.textContent = String(selected.count || 0);
  els.sourceUnique.textContent = String(selected.unique_count || 0);
  els.sourceResume.textContent = `${done}/${total || selected.unique_count || 0} (${ratio})`;
  els.sourceOutputName.textContent = selected.output_exists ? (selected.output_name || "-") : `${selected.output_name || "-"} · 未生成`;
  els.sourceOutputTime.textContent = selected.output_exists
    ? `${formatDateTime(selected.output_modified_at)} · ${formatBytes(selected.output_size_bytes)}`
    : "-";
  renderMetrics(state.lastJob);
  renderGuard();
  syncRunButtons();
}

function renderGuard() {
  const selected = selectedSource();
  const settings = state.settings || {};
  if(els.guardFile) els.guardFile.textContent = selected ? selected.name : "-";
  if(els.guardUnique) els.guardUnique.textContent = String(selected?.unique_count || 0);
  if(els.guardConcurrency) els.guardConcurrency.textContent = String(settings.system_concurrency || "-");
  const providers = Array.isArray(settings.provider_order) ? settings.provider_order.join(" -> ") : "-";
  if(els.guardProviders) els.guardProviders.textContent = providers || "-";
  const ports = Array.isArray(settings.blurpath_proxy_ports) && settings.blurpath_proxy_ports.length
    ? settings.blurpath_proxy_ports.join("/")
    : "-";
  if(els.guardPorts) els.guardPorts.textContent = ports;
}

function latestRuntimeResult(results) {
  return (Array.isArray(results) && results.length) ? results[results.length - 1] : null;
}

function deriveRuntime(job) {
  const results = Array.isArray(job?.results) ? job.results : [];
  const total = Array.isArray(job?.input_cnpjs) ? job.input_cnpjs.length : 0;
  const successCount = results.filter((item) => isBusinessSuccess(item) || item.status === "partial_success").length;
  const last = latestRuntimeResult(results);
  let provider = "-";
  let port = "-";
  if (last?.company?.source_provider) {
    provider = last.company.source_provider;
  } else if (Array.isArray(last?.provider_trace) && last.provider_trace.length) {
    provider = last.provider_trace[last.provider_trace.length - 1].provider || "-";
  }
  if (last?.company?.source_proxy_port) {
    port = String(last.company.source_proxy_port);
  } else if (Array.isArray(last?.provider_trace) && last.provider_trace.length) {
    const portMatch = String(last.provider_trace[last.provider_trace.length - 1].error || "").match(/port=(\d+)/);
    if (portMatch) port = portMatch[1];
  }
  let eta = "-";
  if (job && ["queued", "running", "canceling"].includes(job.status) && results.length > 0 && total > results.length) {
    const elapsed = Math.max(1, Date.now() / 1000 - Number(job.created_at || 0));
    const perItem = elapsed / results.length;
    eta = formatEtaSeconds(perItem * (total - results.length));
  }
  const successRate = results.length ? `${Math.round((successCount / results.length) * 100)}%` : "-";
  return { provider, port, successRate, eta };
}

function renderRuntime(job) {
  const runtime = deriveRuntime(job || state.lastJob || {});
  els.runtimeProvider.textContent = runtime.provider;
  els.runtimePort.textContent = runtime.port;
  els.runtimeSuccessRate.textContent = runtime.successRate;
  els.runtimeEta.textContent = runtime.eta;
}

function applyResultFilter(results) {
  const rows = Array.isArray(results) ? results : [];
  if (state.resultFilter === "issues") {
    return rows.filter((item) => !isBusinessSuccess(item) && item.status !== "partial_success");
  }
  if (state.resultFilter === "partial") {
    return rows.filter((item) => item.status === "partial_success" && !isBusinessSuccess(item));
  }
  if (state.resultFilter === "success") {
    return rows.filter((item) => isBusinessSuccess(item));
  }
  return rows;
}

function syncFilterButtons() {
  const mapping = {
    all: els.failureFilterAll,
    issues: els.failureFilterIssues,
    partial: els.failureFilterPartial,
    success: els.failureFilterSuccess,
  };
  Object.entries(mapping).forEach(([key, button]) => {
    button.classList.toggle("active", state.resultFilter === key);
    if(key === "success") button.classList.toggle("success", state.resultFilter === key);
    if(key === "partial") button.classList.toggle("warning", state.resultFilter === key);
    if(key === "issues") button.classList.toggle("danger", state.resultFilter === key);
  });
  syncRunButtons();
}

function renderResults(job) {
  state.lastJob = job;
  if (job?.job_id) {
    state.jobId = job.job_id;
  }
  const allResults = Array.isArray(job.results) ? job.results : [];
  state.lastResults = allResults;
  if (job.output_path) {
    updateOutputHint(job.output_path);
  }
  const isNameMode = job.mode === "name";
  const rowTotal = isNameMode
    ? Number(job.total_units || allResults.length || 1)
    : (job.input_cnpjs ? job.input_cnpjs.length : Math.max(allResults.length, 1));
  const rowCompleted = allResults.length;
  const uniqueTotal = isNameMode
    ? rowTotal
    : (job.input_cnpjs ? uniqueInputCount(job.input_cnpjs) : Math.max(uniqueItemsByCnpj(allResults).length, 1));
  const uniqueCompleted = isNameMode ? allResults.length : uniqueItemsByCnpj(allResults).length;
  const progressTotal = Math.max(uniqueTotal, 1);
  els.progressBar.style.width = `${Math.min(100, Math.round((uniqueCompleted / progressTotal) * 100))}%`;
  if (uniqueTotal !== rowTotal) {
    els.jobStatus.textContent = `${statusLabel(job.status)} · 公司 ${uniqueCompleted}/${uniqueTotal} · 行 ${rowCompleted}/${rowTotal}`;
  } else {
    els.jobStatus.textContent = `${statusLabel(job.status)} · ${uniqueCompleted}/${uniqueTotal}`;
  }
  
  const pulseDot = document.getElementById("jobPulseDot");
  if(pulseDot) {
      if(["queued", "running", "canceling"].includes(job.status)) {
          pulseDot.classList.add("running");
      } else {
          pulseDot.classList.remove("running");
      }
  }

  renderRuntime(job);
  renderMetrics(job);
  syncFilterButtons();

  const filteredResults = applyResultFilter(allResults);
  if (!filteredResults.length) {
    els.resultBody.innerHTML = '<tr class="empty-row"><td colspan="5">当前筛选下暂无结果</td></tr>';
    renderPagination(0);
    return;
  }

  const pageCount = Math.max(1, Math.ceil(filteredResults.length / state.pageSize));
  if (state.followLatestPage && ["queued", "running", "canceling"].includes(job.status)) {
    state.currentPage = pageCount;
  }
  state.currentPage = Math.min(Math.max(1, state.currentPage), pageCount);
  const pageStart = (state.currentPage - 1) * state.pageSize;
  const visibleResults = filteredResults.slice(pageStart, pageStart + state.pageSize);

  els.resultBody.innerHTML = visibleResults.map((item) => {
    const company = item.company || {};
    const responsible = item.responsible || {};
    const meta = item.name_meta || {};
    const isNameRow = Boolean(meta.query_name);
    const names = (responsible.names || []).join("; ");
    const matchedCnpj = meta.matched_cnpj || item.normalized_cnpj || "";
    const companyName = (isNameRow ? meta.matched_company_name : "") || company.trade_name || company.legal_name || "";
    const url = company.url || (matchedCnpj ? `https://cnpj.biz/${matchedCnpj}` : "");
    const businessSuccess = isBusinessSuccess(item);
    const displayStatus = businessSuccess ? "success" : item.status;
    const issueText = businessSuccess ? "" : (item.error || "");
    // LLM is disabled (rule-based ranking only); the analysis-source label is hidden.
    const analysisMeta = "";
    const fetchMeta = company.source_provider
      ? `<div style="margin-top:4px;color:var(--text-muted);font-size:12px;">${escapeHtml(company.source_provider)}${company.source_proxy_port ? ` · port ${escapeHtml(company.source_proxy_port)}` : ""}</div>`
      : "";

    let statusClass = "status-neutral";
    if(businessSuccess) statusClass = "status-success";
    if(!businessSuccess && (item.status === "partial_success" || item.status === "blocked_by_cloudflare")) statusClass = "status-warning";
    if(item.status === "failed" || item.status === "fetch_error" || item.status === "not_found") statusClass = "status-danger";
    const retryAction = (businessSuccess || isNameRow)
      ? ""
      : `<div style="margin-top:8px;"><button class="btn btn-secondary btn-xs retry-single-button" data-cnpj="${escapeHtml(item.normalized_cnpj || item.input_cnpj || "")}" type="button">重跑本条</button></div>`;

    const firstCell = isNameRow
      ? `<div style="font-weight:500;">${escapeHtml(meta.query_name)}</div>` +
        (matchedCnpj
          ? `<div style="margin-top:4px;font-size:12px;"><a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(item.input_cnpj || matchedCnpj)}</a></div>`
          : `<div style="margin-top:4px;font-size:12px;color:var(--text-muted);">未匹配到公司</div>`)
      : `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(item.input_cnpj || item.normalized_cnpj)}</a>`;

    return `
      <tr>
        <td>${firstCell}</td>
        <td>
          <div style="font-weight:500;">${escapeHtml(companyName)}</div>
          <div style="color:var(--text-muted);font-size:12px;margin-top:4px;">${escapeHtml(company.city || "")}${company.state ? " / " + escapeHtml(company.state) : ""}</div>
          ${fetchMeta}
        </td>
        <td>${escapeHtml(names || "-")}</td>
        <td>${escapeHtml(responsible.role || "-")}</td>
        <td class="status-cell">
          <span class="status-badge ${statusClass}">${escapeHtml(statusLabel(displayStatus))}</span>
          ${issueText ? `<div class="status-detail">${escapeHtml(issueText)}</div>` : ""}
          ${analysisMeta}
          ${retryAction}
        </td>
      </tr>
    `;
  }).join("");
  els.resultBody.querySelectorAll(".retry-single-button").forEach((button) => {
    button.addEventListener("click", () => startAdhocRetryJob(button.dataset.cnpj || ""));
  });
  renderPagination(pageCount);
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    state.health = data;
    const proxy = data.browser_proxy || {};
    const ports = Array.isArray(proxy.ports) && proxy.ports.length ? `:${proxy.ports.join("/")}` : "";
    els.apiBadge.textContent = `就绪 · ${data.system_concurrency}并发 · ${ports}`;
    const dot = document.getElementById("apiBadgeDot");
    if(dot) dot.className = "status-dot active";
    els.blurpathStatus.textContent = data.blurpath_proxy_configured ? `已配置 · ${proxy.ports.join("/")}` : "未配置";
    renderGuard();
  } catch {
    els.apiBadge.textContent = "离线";
    const dot = document.getElementById("apiBadgeDot");
    if(dot) dot.className = "status-dot warn";
    els.blurpathStatus.textContent = "离线";
  }
}

async function loadSettings() {
  try {
    const response = await fetch("/api/settings");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "设置读取失败");
    state.settings = data;
    syncApiKeyField(data.llm_api_key || "");
    els.proxyHostInput.value = data.blurpath_proxy_host || "";
    els.proxyRegionInput.value = data.blurpath_proxy_region || "";
    els.proxyUsernameInput.value = data.blurpath_proxy_username || "";
    syncProxyPasswordField(data.blurpath_proxy_password || "");
    els.proxyProtocolInput.value = data.blurpath_proxy_protocol || "http";
    els.proxySessionInput.value = data.blurpath_proxy_session_time_minutes || 10;
    els.modelInput.value = data.llm_model || "";
    els.concurrencyInput.value = data.system_concurrency || 1;
    const availablePorts = Array.isArray(data.blurpath_available_proxy_ports) ? data.blurpath_available_proxy_ports : [];
    els.blurpathPortsHint.textContent = availablePorts.length ? `可用端口: ${availablePorts.join(",")}` : "可用端口未知";
    els.blurpathPortsInput.placeholder = availablePorts.length ? availablePorts.join(",") : "15129";
    els.blurpathPortsInput.value = Array.isArray(data.blurpath_proxy_ports) ? data.blurpath_proxy_ports.join(",") : "";
    els.settingsStatus.textContent = "设置已加载";
    renderGuard();
  } catch (error) {
    els.blurpathPortsHint.textContent = "可用端口读取失败";
    els.settingsStatus.textContent = error.message;
  }
}

async function saveSettings() {
  els.saveSettingsButton.disabled = true;
  els.settingsStatus.textContent = "保存中";
  try {
    const payload = {
      llm_model: els.modelInput.value.trim() || "gpt-5.4-mini",
      blurpath_proxy_host: els.proxyHostInput.value.trim(),
      blurpath_proxy_region: els.proxyRegionInput.value.trim(),
      blurpath_proxy_username: els.proxyUsernameInput.value.trim(),
      blurpath_proxy_protocol: els.proxyProtocolInput.value.trim() || "http",
      blurpath_proxy_session_time_minutes: Number(els.proxySessionInput.value || "10"),
      system_concurrency: Number(els.concurrencyInput.value || "1"),
      blurpath_proxy_ports: (els.blurpathPortsInput.value || "")
        .split(",")
        .map((item) => Number(item.trim()))
        .filter((item) => Number.isInteger(item) && item > 0),
    };
    const apiKeyValue = els.apiKeyInput.value.trim();
    if (!(state.apiKeyMasked && !state.apiKeyDirty && !apiKeyValue)) {
      payload.llm_api_key = apiKeyValue;
    }
    const proxyPasswordValue = els.proxyPasswordInput.value.trim();
    if (!(state.proxyPasswordMasked && !state.proxyPasswordDirty && !proxyPasswordValue)) {
      payload.blurpath_proxy_password = proxyPasswordValue;
    }
    const response = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "设置保存失败");
    state.settings = data;
    syncApiKeyField(data.llm_api_key || "");
    els.proxyHostInput.value = data.blurpath_proxy_host || "";
    els.proxyRegionInput.value = data.blurpath_proxy_region || "";
    els.proxyUsernameInput.value = data.blurpath_proxy_username || "";
    syncProxyPasswordField(data.blurpath_proxy_password || "");
    els.proxyProtocolInput.value = data.blurpath_proxy_protocol || "http";
    els.proxySessionInput.value = data.blurpath_proxy_session_time_minutes || 10;
    els.modelInput.value = data.llm_model || "";
    els.concurrencyInput.value = data.system_concurrency || 1;
    const availablePorts = Array.isArray(data.blurpath_available_proxy_ports) ? data.blurpath_available_proxy_ports : [];
    els.blurpathPortsHint.textContent = availablePorts.length ? `可用端口: ${availablePorts.join(",")}` : "可用端口未知";
    els.blurpathPortsInput.placeholder = availablePorts.length ? availablePorts.join(",") : "15129";
    els.blurpathPortsInput.value = Array.isArray(data.blurpath_proxy_ports) ? data.blurpath_proxy_ports.join(",") : "";
    els.settingsStatus.textContent = "设置已保存";
    renderGuard();
    await loadHealth();
  } catch (error) {
    els.settingsStatus.textContent = error.message;
  } finally {
    els.saveSettingsButton.disabled = false;
  }
}

async function runProxyPreflight() {
  els.proxyPreflightButton.disabled = true;
  els.blurpathStatus.textContent = "检查中";
  els.proxyProbeList.innerHTML = "";
  try {
    const response = await fetch("/api/proxy-preflight");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "代理预检失败");
    els.blurpathStatus.textContent = data.proxy_probe_ok ? `已就绪 · ${data.ports.join("/")}` : data.proxy_error || "失败";
    renderProxyProbeResults(data.proxy_probe_results);
  } catch (error) {
    els.blurpathStatus.textContent = error.message;
  } finally {
    els.proxyPreflightButton.disabled = false;
  }
}

async function loadSourceFiles() {
  els.sourceFileSelect.disabled = true;
  try {
    const response = await fetch("/api/source-files");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "文件列表读取失败");
    const previous = state.selectedSourceName;
    state.sourceFiles = Array.isArray(data.files) ? data.files : [];
    els.sourceDirHint.textContent = `输入目录: ${data.input_dir} · 输出目录: ${data.output_dir}`;
    els.sourceFileSelect.innerHTML = "";
    if (!state.sourceFiles.length) {
      els.sourceFileSelect.innerHTML = '<option value="">暂无可用文件</option>';
      state.selectedSourceName = "";
      renderSourceSummary();
      return;
    }
    els.sourceFileSelect.innerHTML = state.sourceFiles.map((item) => (
      `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`
    )).join("");
    state.selectedSourceName = state.sourceFiles.some((item) => item.name === previous)
      ? previous
      : state.sourceFiles[0].name;
    els.sourceFileSelect.value = state.selectedSourceName;
    renderSourceSummary();
  } catch (error) {
    els.sourceDirHint.textContent = error.message;
    els.sourceFileSelect.innerHTML = '<option value="">读取失败</option>';
    state.selectedSourceName = "";
    renderSourceSummary();
  } finally {
    els.sourceFileSelect.disabled = false;
  }
}

async function loadOutputFiles() {
  try {
    const response = await fetch("/api/output-files");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "产物列表读取失败");
    state.outputFiles = Array.isArray(data.files) ? data.files : [];
    renderOutputFiles();
  } catch (error) {
    els.outputList.innerHTML = `<div class="empty-state-dark">${escapeHtml(error.message)}</div>`;
  }
}

async function openOutputDirectory() {
  els.openOutputDirButton.disabled = true;
  try {
    const response = await fetch("/api/output-directory/open", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "打开目录失败");
  } catch (error) {
    alert(error.message);
  } finally {
    els.openOutputDirButton.disabled = false;
  }
}

async function openOutputFile(filename) {
  if (!filename) return;
  try {
    const response = await fetch(`/api/output-files/${encodeURIComponent(filename)}/open`, { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "打开文件失败");
  } catch (error) {
    alert(error.message);
  }
}

function enqueueSource(name) {
  if (!name) return;
  appendQueueItem(sourceQueueItem(name));
  renderQueue();
}

function removeFromQueue(index) {
  if (Number.isNaN(index) || isRunActive()) return;
  state.sourceQueue.splice(index, 1);
  renderQueue();
}

async function readJsonResponse(response, fallbackMessage) {
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) {
    throw new Error(data.detail || fallbackMessage);
  }
  return data;
}

function beginPolling(jobId) {
  clearPollTimer();
  if (state.jobId !== jobId || !isJobActive()) {
    return;
  }
  state.pollTimer = window.setInterval(() => {
    pollJob(jobId);
  }, 5000);
}

async function handleCreatedJob(job) {
  state.submitting = false;
  state.jobId = job.job_id;
  renderResults(job);
  if (isJobTerminal(job)) {
    await finishTerminalJob(job);
  } else {
    beginPolling(job.job_id);
  }
  return job;
}

function markActiveQueueItem(status, jobId = state.jobId) {
  const current = activeQueueItem();
  if (!current) return;
  current.status = status;
  current.jobId = jobId || current.jobId || "";
  renderQueue();
}

async function finishTerminalJob(job) {
  clearPollTimer();
  if (job.job_id && state.jobId !== job.job_id) return;
  const current = activeQueueItem();
  if (current) {
    current.status = job.status === "completed" ? "completed" : job.status === "canceled" ? "canceled" : "failed";
    current.jobId = job.job_id;
    renderQueue();
    const retryItem = buildFailedRetryQueueItem(job, Number(current.retryAttempt || 0) + 1);
    if (retryItem && appendQueueItem(retryItem)) {
      renderQueue();
    }
  }
  const remaining = queuedSources().length > 0;
  if (state.queueRunning && remaining) {
    await Promise.all([loadSourceFiles(), loadOutputFiles()]);
    await startQueueRun();
    return;
  }
  state.queueRunning = false;
  await Promise.all([loadSourceFiles(), loadOutputFiles()]);
  syncRunButtons();
}

async function startSourceJob(sourceName) {
  const response = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_name: sourceName }),
  });
  const job = await readJsonResponse(response, "任务创建失败");
  return handleCreatedJob(job);
}

async function startFailedRetryJob(parentJobId) {
  const response = await fetch(`/api/jobs/${parentJobId}/retry-failed`, { method: "POST" });
  const job = await readJsonResponse(response, "重跑失败任务创建失败");
  return handleCreatedJob(job);
}

async function startAdhocRetryJob(cnpj) {
  if (!cnpj || isRunActive()) return;
  const currentJobId = state.jobId;
  clearPollTimer();
  els.jobStatus.textContent = "单条重跑提交中";
  els.progressBar.style.width = "0%";
  state.currentPage = 1;
  state.followLatestPage = true;
  state.submitting = true;
  state.queueRunning = false;
  syncRunButtons();
  try {
    const response = currentJobId
      ? await fetch(`/api/jobs/${currentJobId}/retry-one`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cnpj }),
      })
      : await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cnpjs: [cnpj] }),
      });
    const job = await readJsonResponse(response, "单条重跑任务创建失败");
    await handleCreatedJob(job);
  } catch (error) {
    state.submitting = false;
    alert(error.message);
    syncRunButtons();
  }
}

async function startQueueRun() {
  const next = state.sourceQueue.find((item) => item.status === "queued");
  if (!next) {
    state.queueRunning = false;
    state.submitting = false;
    renderQueue();
    syncRunButtons();
    return;
  }
  next.status = "running";
  renderQueue();
  try {
    const job = next.kind === "retry_failed"
      ? await startFailedRetryJob(next.parentJobId)
      : await startSourceJob(next.name);
    next.jobId = job.job_id;
    renderQueue();
  } catch (error) {
    next.status = "failed";
    state.queueRunning = false;
    renderQueue();
    syncRunButtons();
    throw error;
  }
}

async function startJob() {
  if (isRunActive()) {
    return;
  }
  if (!state.selectedSourceName && !queuedSources().length) {
    els.jobStatus.textContent = "请先选择待爬文件";
    syncRunButtons();
    return;
  }
  clearPollTimer();
  els.jobStatus.textContent = "提交中";
  els.progressBar.style.width = "0%";
  state.currentPage = 1;
  state.followLatestPage = true;
  state.submitting = true;
  syncRunButtons();
  try {
    if (!queuedSources().length && state.selectedSourceName) {
      enqueueSource(state.selectedSourceName);
    }
    state.queueRunning = true;
    syncRunButtons();
    await startQueueRun();
  } catch (error) {
    alert(error.message);
    state.submitting = false;
    state.queueRunning = false;
    syncRunButtons();
  }
}

async function stopJob() {
  if (!state.jobId || !isJobActive()) return;
  const wasQueueRunning = state.queueRunning;
  state.queueRunning = false;
  els.jobStatus.textContent = "停止中";
  syncRunButtons();
  try {
    const response = await fetch(`/api/jobs/${state.jobId}/cancel`, { method: "POST" });
    const job = await readJsonResponse(response, "停止任务失败");
    renderResults(job);
    if (isJobTerminal(job)) {
      await finishTerminalJob(job);
    } else {
      beginPolling(job.job_id);
    }
  } catch (error) {
    alert(error.message);
    state.queueRunning = wasQueueRunning;
    syncRunButtons();
  }
}

async function pollJob(expectedJobId = state.jobId) {
  if (!expectedJobId || state.pollInFlight) return;
  state.pollInFlight = true;
  try {
    const response = await fetch(`/api/jobs/${expectedJobId}`);
    const job = await readJsonResponse(response, "任务状态读取失败");
    if (state.jobId !== expectedJobId) return;
    renderResults(job);
    if (isJobTerminal(job)) {
      await finishTerminalJob(job);
    }
  } catch (error) {
    clearPollTimer();
    state.queueRunning = false;
    markActiveQueueItem("failed", expectedJobId);
    els.jobStatus.textContent = error.message;
    syncRunButtons();
  } finally {
    state.pollInFlight = false;
  }
}

async function copyFailedCnpjs() {
  const failedRows = hardFailedResults();
  if (!failedRows.length) return;
  const text = failedRows.map((item) => item.input_cnpj || item.normalized_cnpj).join("\n");
  await navigator.clipboard.writeText(text);
}

async function runFailedJob() {
  if (!state.jobId || isRunActive() || !isJobTerminal()) return;
  state.submitting = true;
  syncRunButtons();
  try {
    const response = await fetch(`/api/jobs/${state.jobId}/retry-failed`, { method: "POST" });
    const job = await readJsonResponse(response, "重跑失败任务创建失败");
    clearPollTimer();
    state.queueRunning = false;
    await handleCreatedJob(job);
  } catch (error) {
    state.submitting = false;
    alert(error.message);
    syncRunButtons();
  }
}

function clearAll() {
  if (isRunActive()) {
    els.jobStatus.textContent = "请先停止当前任务";
    syncRunButtons();
    return;
  }
  clearPollTimer();
  state.jobId = null;
  state.lastResults = [];
  state.lastJob = null;
  state.currentPage = 1;
  state.followLatestPage = true;
  state.resultFilter = "all";
  state.sourceQueue = [];
  state.queueRunning = false;
  state.submitting = false;
  els.progressBar.style.width = "0%";
  els.jobStatus.textContent = "等待输入";
  els.resultBody.innerHTML = '<tr class="empty-row"><td colspan="5">暂无结果</td></tr>';
  const pulseDot = document.getElementById("jobPulseDot");
  if(pulseDot) pulseDot.classList.remove("running");
  renderPagination(0);
  renderRuntime(null);
  syncFilterButtons();
  renderSourceSummary();
  renderQueue();
  renderMetrics(null);
  syncRunButtons();
}

function setFilter(filter) {
  state.resultFilter = filter;
  state.currentPage = 1;
  state.followLatestPage = false;
  syncFilterButtons();
  renderResults(state.lastJob || { results: state.lastResults, status: "completed", input_cnpjs: state.lastResults });
}

els.startButton.addEventListener("click", startJob);
els.stopButton.addEventListener("click", stopJob);
els.clearButton.addEventListener("click", clearAll);
els.saveSettingsButton.addEventListener("click", saveSettings);
els.apiKeyInput.addEventListener("input", () => {
  state.apiKeyDirty = true;
});
els.proxyPasswordInput.addEventListener("input", () => {
  state.proxyPasswordDirty = true;
});
els.proxyPreflightButton.addEventListener("click", runProxyPreflight);
els.sourceFileSelect.addEventListener("change", () => {
  state.selectedSourceName = els.sourceFileSelect.value;
  renderSourceSummary();
});
els.queueSourceButton.addEventListener("click", () => {
  enqueueSource(state.selectedSourceName);
});
els.openOutputDirButton.addEventListener("click", openOutputDirectory);
els.failureFilterAll.addEventListener("click", () => setFilter("all"));
els.failureFilterIssues.addEventListener("click", () => setFilter("issues"));
els.failureFilterPartial.addEventListener("click", () => setFilter("partial"));
els.failureFilterSuccess.addEventListener("click", () => setFilter("success"));
els.copyFailedButton.addEventListener("click", copyFailedCnpjs);
els.runFailedButton.addEventListener("click", runFailedJob);
els.prevPageButton.addEventListener("click", () => {
  state.followLatestPage = false;
  state.currentPage -= 1;
  renderResults(state.lastJob || { results: state.lastResults, status: "completed", input_cnpjs: state.lastResults });
});
els.nextPageButton.addEventListener("click", () => {
  state.followLatestPage = false;
  state.currentPage += 1;
  renderResults(state.lastJob || { results: state.lastResults, status: "completed", input_cnpjs: state.lastResults });
});

loadHealth();
loadSettings();
loadSourceFiles();
loadOutputFiles();
renderRuntime(null);
renderPagination(0);
syncFilterButtons();
renderQueue();
