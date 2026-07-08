let strategies = {
  "ha-premium": {
    title: "H/A 溢价目标权重",
    command: "run",
    description: "每个交易日按 H/A 溢价排序，取前 10 只并根据 Top30 均值偏移分配仓位。",
  },
  "ha-premium-annual-line": {
    title: "H/A 溢价年线过滤",
    command: "run",
    description: "每个交易日先按 H/A 溢价排序取前 10 只并根据 Top30 均值偏移计算仓位，再仅对 A 股收盘价高于 250 日均线的标的执行目标仓位。",
  },
};

const els = {
  strategySelect: document.querySelector("#strategySelect"),
  strategyMeta: document.querySelector("#strategyMeta"),
  startDate: document.querySelector("#startDate"),
  endDate: document.querySelector("#endDate"),
  initialCash: document.querySelector("#initialCash"),
  refreshData: document.querySelector("#refreshData"),
  commandText: document.querySelector("#commandText"),
  copyCommand: document.querySelector("#copyCommand"),
  runButton: document.querySelector("#runButton"),
  pageTitle: document.querySelector("#pageTitle"),
  statusPill: document.querySelector("#statusPill"),
  sampleDays: document.querySelector("#sampleDays"),
  outputCard: document.querySelector("#outputCard"),
  outputDir: document.querySelector("#outputDir"),
  outputHint: document.querySelector("#outputHint"),
  reportCard: document.querySelector("#reportCard"),
  reportState: document.querySelector("#reportState"),
  reportHint: document.querySelector("#reportHint"),
  progressCaption: document.querySelector("#progressCaption"),
  progressPercent: document.querySelector("#progressPercent"),
  progressBar: document.querySelector("#progressBar"),
  totalReturn: document.querySelector("#totalReturn"),
  annualizedReturn: document.querySelector("#annualizedReturn"),
  maxDrawdown: document.querySelector("#maxDrawdown"),
  sharpeRatio: document.querySelector("#sharpeRatio"),
  weightsTable: document.querySelector("#weightsTable"),
  reportChartCaption: document.querySelector("#reportChartCaption"),
  exposureChartCaption: document.querySelector("#exposureChartCaption"),
  reportCanvas: document.querySelector("#reportEquityChart"),
  exposureCanvas: document.querySelector("#exposureChart"),
};

let pollTimer = null;
let currentJobId = null;

function toCliDate(value) {
  return value.replaceAll("-", "");
}

function formatDateInput(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function oneYearAgo(date) {
  const result = new Date(date.getFullYear() - 1, date.getMonth(), date.getDate());
  if (result.getMonth() !== date.getMonth()) {
    return new Date(date.getFullYear() - 1, date.getMonth() + 1, 0);
  }
  return result;
}

function initializeDefaultDates(today = new Date()) {
  const currentDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  els.endDate.value = formatDateInput(currentDate);
  els.startDate.value = formatDateInput(oneYearAgo(currentDate));
}
function getDurationDays() {
  const start = new Date(els.startDate.value);
  const end = new Date(els.endDate.value);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return 0;
  return Math.max(0, Math.round((end - start) / 86400000) + 1);
}

function buildCommand() {
  const strategy = strategies[els.strategySelect.value];
  const parts = [
    "python -X utf8 -m ha_backtest.cli",
    strategy.command,
    "--start",
    toCliDate(els.startDate.value),
    "--end",
    toCliDate(els.endDate.value),
  ];

  if (strategy.command === "run") {
    parts.push("--initial-cash", String(Number(els.initialCash.value || 0)));
  }

  if (els.refreshData.checked) parts.push("--refresh");

  return parts.join(" ");
}

function cleanStrategyTitle(title) {
  return String(title || "").replaceAll("回测", "");
}

function syncForm() {
  const strategy = strategies[els.strategySelect.value] || Object.values(strategies)[0];
  if (!strategy) return;
  els.pageTitle.textContent = strategy.title;
  els.strategyMeta.textContent = strategy.description;
  els.sampleDays.textContent = `${getDurationDays()} 天`;
  els.commandText.textContent = buildCommand();
}

function setStatus(kind, text) {
  els.statusPill.className = `status-pill ${kind}`;
  els.statusPill.querySelector("strong").textContent = text;
}

function resetResult() {
  clearInterval(pollTimer);
  pollTimer = null;
  currentJobId = null;
  els.runButton.disabled = false;
  setStatus("idle", "待执行");
  els.progressPercent.textContent = "0%";
  els.progressBar.style.width = "0%";
  els.progressCaption.textContent = "选择参数后点击开始执行。";
  setOutputDirectory(null, null);
  els.reportCard.disabled = true;
  els.reportCard.classList.remove("ready");
  els.reportCard.onclick = null;
  els.reportCard.setAttribute("aria-label", "AKQuant 报告未生成");
  els.reportState.textContent = "未生成";
  els.reportHint.textContent = "AKQuant HTML";
  els.totalReturn.textContent = "--";
  els.annualizedReturn.textContent = "--";
  els.maxDrawdown.textContent = "--";
  els.sharpeRatio.textContent = "--";
  els.reportChartCaption.textContent = "";
  els.exposureChartCaption.textContent = "等待执行结果";
  els.weightsTable.innerHTML = emptyTableRow("执行完成后显示最新目标持仓。", 5);
  drawLineChart(els.reportCanvas, [], { emptyText: "执行完成后显示 AKQuant 权益曲线", xLabel: "日期", yLabel: "权益", minValue: 0, maxValue: 1 });
  drawLineChart(els.exposureCanvas, [], { emptyText: "执行完成后显示每日目标仓位", xLabel: "日期", yLabel: "仓位", minValue: 0, maxValue: 1 });
}


function requestPayload() {
  return {
    strategy: els.strategySelect.value,
    startDate: els.startDate.value,
    endDate: els.endDate.value,
    initialCash: Number(els.initialCash.value || 0),
    refreshData: els.refreshData.checked,
  };
}

async function startRun() {
  if (getDurationDays() <= 0) {
    els.progressCaption.textContent = "结束日期需要晚于或等于开始日期。";
    setStatus("idle", "参数错误");
    return;
  }

  resetResult();
  els.runButton.disabled = true;
  setStatus("running", "提交中");
  els.progressCaption.textContent = "正在提交任务到本地后端。";

  try {
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestPayload()),
    });
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || "任务提交失败。");
    currentJobId = job.id;
    applyJob(job);
    pollTimer = setInterval(pollJob, 1200);
  } catch (error) {
    setStatus("idle", "提交失败");
    els.progressCaption.textContent = error.message;
    els.runButton.disabled = false;
  }
}

async function pollJob() {
  if (!currentJobId) return;
  try {
    const response = await fetch(`/api/jobs/${currentJobId}`);
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || "读取任务状态失败。");
    applyJob(job);
    if (["completed", "failed"].includes(job.status)) {
      clearInterval(pollTimer);
      pollTimer = null;
      els.runButton.disabled = false;
    }
  } catch (error) {
    clearInterval(pollTimer);
    pollTimer = null;
    setStatus("idle", "连接失败");
    els.progressCaption.textContent = error.message;
    els.runButton.disabled = false;
  }
}

function applyJob(job) {
  const progress = Number(job.progress || 0);
  els.progressPercent.textContent = `${progress}%`;
  els.progressBar.style.width = `${progress}%`;
  els.progressCaption.textContent = job.error || job.message || "任务状态更新中。";
  if (job.output_dir) setOutputDirectory(job, false);

  if (job.status === "queued" || job.status === "running") setStatus("running", "执行中");
  if (job.status === "completed") {
    setStatus("done", "已完成");
    renderResult(job);
  }
  if (job.status === "failed") setStatus("idle", "执行失败");
}

function setOutputDirectory(job, ready, outputPath) {
  if (!job || (!outputPath && ready !== false)) {
    els.outputCard.disabled = true;
    els.outputCard.classList.remove("ready");
    els.outputCard.onclick = null;
    els.outputCard.removeAttribute("title");
    els.outputCard.setAttribute("aria-label", "\u8f93\u51fa\u76ee\u5f55\u672a\u751f\u6210");
    els.outputDir.textContent = "\u5f85\u751f\u6210";
    els.outputHint.textContent = "\u6267\u884c\u5b8c\u6210\u540e\u751f\u6210";
    return;
  }

  const path = outputPath || job.output_dir || "";
  els.outputCard.title = path;
  els.outputCard.classList.toggle("ready", Boolean(ready));
  els.outputCard.disabled = !ready;
  els.outputCard.setAttribute("aria-label", ready ? "打开报告所在文件夹" : "输出目录已创建，等待任务完成");
  els.outputDir.textContent = ready ? "\u6253\u5f00\u76ee\u5f55" : "\u5df2\u521b\u5efa";
  els.outputHint.textContent = ready ? "点击打开报告所在文件夹" : "\u7b49\u5f85\u4efb\u52a1\u5b8c\u6210";
  els.outputCard.onclick = ready ? () => openOutputDirectory(job.id) : null;
}

async function openOutputDirectory(jobId) {
  try {
    const response = await fetch(`/api/jobs/${jobId}/open-output-dir`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "\u6253\u5f00\u8f93\u51fa\u76ee\u5f55\u5931\u8d25\u3002");
    els.outputHint.textContent = "已请求打开报告所在文件夹";
  } catch (error) {
    els.outputHint.textContent = error.message;
  }
}

function renderResult(job) {
  const result = job.result || {};
  const metrics = result.metrics || {};
  setOutputDirectory(job, true, result.outputDir || job.output_dir || "");
  const reportReady = hasFile(result, "akquant_ha_report.html");
  els.reportState.textContent = reportReady ? "已生成" : "未生成";
  els.reportHint.textContent = reportReady ? "点击打开完整回测报告" : "AKQuant HTML";
  els.reportCard.disabled = !reportReady;
  els.reportCard.classList.toggle("ready", reportReady);
  els.reportCard.setAttribute("aria-label", reportReady ? "打开完整回测报告" : "AKQuant 报告未生成");
  els.reportCard.onclick = reportReady ? () => window.open(`/api/files/${job.id}/akquant_ha_report.html`, "_blank") : null;
  const reportMetrics = result.reportMetrics || {};
  els.totalReturn.textContent = reportMetrics.totalReturn || "--";
  els.annualizedReturn.textContent = reportMetrics.annualizedReturn || "--";
  els.maxDrawdown.textContent = reportMetrics.maxDrawdown || "--";
  els.sharpeRatio.textContent = reportMetrics.sharpe || "--";
  els.reportChartCaption.textContent = "";
  els.exposureChartCaption.textContent = result.latestDate ? `截至 ${result.latestDate} 的每日目标仓位` : "本次任务无可展示仓位曲线";
  renderWeights(result.weights || []);
  drawLineChart(els.reportCanvas, result.equitySeries || [], { emptyText: "执行完成后显示 AKQuant 权益曲线", color: "#11685f", xLabel: "日期", yLabel: "权益" });
  drawLineChart(els.exposureCanvas, result.exposureSeries || [], { emptyText: "执行完成后显示每日目标仓位", color: "#3776ab", minValue: 0, maxValue: 1, xLabel: "日期", yLabel: "仓位" });
}

function renderWeights(rows) {
  if (!rows.length) {
    els.weightsTable.innerHTML = emptyTableRow("本次任务没有生成目标持仓。", 5);
    return;
  }
  els.weightsTable.innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td>${escapeHtml(row.symbol || "")}</td>
          <td>${escapeHtml(row.name || row.symbol || "")}</td>
          <td>${formatPercentFromRate(row.premiumRate)}</td>
          <td>${formatPercent(row.targetWeight)}</td>
          <td><span class="badge">目标持仓</span></td>
        </tr>
      `,
    )
    .join("");
}


function hasFile(result, filename) {
  return Boolean((result.files || []).find((file) => file.name === filename && file.exists));
}

function drawLineChart(canvas, series, options = {}) {
  const context = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const pad = { top: 24, right: 26, bottom: 46, left: 72 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const points = series
    .map((point) => (typeof point === "number" ? { value: point } : point))
    .filter((point) => point && point.value !== null && point.value !== undefined && !Number.isNaN(Number(point.value)));
  const values = points.map((point) => Number(point.value));
  const hasData = values.length > 0;
  let min = hasData ? Math.min(...values) : 0;
  let max = hasData ? Math.max(...values) : 1;

  const hasFixedBounds = options.minValue !== undefined && options.maxValue !== undefined;

  if (options.minValue !== undefined) min = Number(options.minValue);
  else if (options.minBase !== undefined) min = Math.min(Number(options.minBase), min);
  if (options.maxValue !== undefined) max = Number(options.maxValue);

  if (!hasFixedBounds) {
    if (min === max) {
      min -= Math.abs(min || 1) * 0.02;
      max += Math.abs(max || 1) * 0.02;
    } else {
      const padding = (max - min) * 0.06;
      min -= padding;
      max += padding;
    }
  }

  const toX = (index) => pad.left + (plotWidth * index) / Math.max(1, points.length - 1);
  const toY = (value) => pad.top + plotHeight - (plotHeight * (value - min)) / (max - min || 1);

  context.clearRect(0, 0, width, height);
  context.fillStyle = "#f8fafc";
  context.fillRect(0, 0, width, height);
  context.strokeStyle = "#d9e0e8";
  context.lineWidth = 1;

  context.font = "12px Microsoft YaHei, Arial";
  context.fillStyle = "#667085";
  context.textAlign = "right";
  context.textBaseline = "middle";
  for (let i = 0; i < 5; i += 1) {
    const y = pad.top + (plotHeight / 4) * i;
    const tickValue = max - ((max - min) / 4) * i;
    context.beginPath();
    context.moveTo(pad.left, y);
    context.lineTo(width - pad.right, y);
    context.stroke();
    context.fillText(formatAxisValue(tickValue, options), pad.left - 10, y);
  }

  context.strokeStyle = "#aeb8c4";
  context.beginPath();
  context.moveTo(pad.left, pad.top);
  context.lineTo(pad.left, height - pad.bottom);
  context.lineTo(width - pad.right, height - pad.bottom);
  context.stroke();

  context.fillStyle = "#667085";
  context.textAlign = "center";
  context.textBaseline = "top";
  context.fillText(options.xLabel || "日期", pad.left + plotWidth / 2, height - 18);
  context.save();
  context.translate(18, pad.top + plotHeight / 2);
  context.rotate(-Math.PI / 2);
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(options.yLabel || "数值", 0, 0);
  context.restore();

  if (points.length) {
    context.textAlign = "left";
    context.textBaseline = "top";
    context.fillText(formatAxisDate(points[0].date), pad.left, height - pad.bottom + 8);
    context.textAlign = "right";
    context.fillText(formatAxisDate(points.at(-1).date), width - pad.right, height - pad.bottom + 8);
  }

  if (!hasData) {
    context.fillStyle = "#667085";
    context.font = "16px Microsoft YaHei, Arial";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(options.emptyText || "执行完成后显示曲线", pad.left + plotWidth / 2, pad.top + plotHeight / 2);
    return;
  }

  context.beginPath();
  values.forEach((value, index) => {
    const x = toX(index);
    const y = toY(value);
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  context.strokeStyle = options.color || "#11685f";
  context.lineWidth = 4;
  context.stroke();

  const lastX = toX(values.length - 1);
  const lastY = toY(values.at(-1));
  context.fillStyle = options.color || "#11685f";
  context.beginPath();
  context.arc(lastX, lastY, 6, 0, Math.PI * 2);
  context.fill();
}

function formatAxisValue(value, options = {}) {
  if (options.yLabel === "仓位") return `${(Number(value) * 100).toFixed(0)}%`;
  const abs = Math.abs(Number(value));
  if (abs >= 1000000) return `${(Number(value) / 1000000).toFixed(2)}M`;
  if (abs >= 1000) return `${(Number(value) / 1000).toFixed(0)}K`;
  return Number(value).toFixed(2);
}

function formatAxisDate(value) {
  return value ? String(value).slice(0, 10) : "";
}

function emptyTableRow(text, columns) {
  return `<tr><td colspan="${columns}">${escapeHtml(text)}</td></tr>`;
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toLocaleString("zh-CN");
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function formatPercentFromRate(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${Number(value).toFixed(2)}%`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  }[char]));
}


async function loadStrategies() {
  try {
    const response = await fetch("/api/strategies");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "读取策略列表失败。");
    const nextStrategies = {};
    payload.strategies.forEach((item) => {
      nextStrategies[item.id] = {
        title: cleanStrategyTitle(item.name),
        command: item.command || "run",
        description: item.description || "",
      };
    });
    if (Object.keys(nextStrategies).length) {
      strategies = nextStrategies;
      els.strategySelect.innerHTML = Object.entries(strategies)
        .map(([id, item]) => `<option value="${escapeHtml(id)}">${escapeHtml(item.title)}</option>`)
        .join("");
    }
  } catch (error) {
    els.progressCaption.textContent = error.message;
  }
  syncForm();
  syncHistoryStrategyOptions();
  renderHistory();
}

document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
    button.classList.add("active");
    document.querySelector(`#${button.dataset.tab}`).classList.add("active");
  });
});

[
  els.strategySelect,
  els.startDate,
  els.endDate,
  els.initialCash,
  els.refreshData,
].forEach((control) => control.addEventListener("input", syncForm));

els.copyCommand.addEventListener("click", async () => {
  await navigator.clipboard.writeText(els.commandText.textContent);
  els.copyCommand.textContent = "✓";
  setTimeout(() => {
    els.copyCommand.textContent = "⧉";
  }, 900);
});

els.runButton.addEventListener("click", startRun);


let historyRuns = [];


let statusTimer = null;

const statusEls = {
  generatedAt: document.querySelector("#statusGeneratedAt"),
  activeJobs: document.querySelector("#statusActiveJobs"),
  latestRun: document.querySelector("#statusLatestRun"),
  latestRunState: document.querySelector("#statusLatestRunState"),
  reportReady: document.querySelector("#statusReportReady"),
  taskBody: document.querySelector("#statusTaskBody"),
};

function startStatusPolling() {
  stopStatusPolling();
  loadStatus();
  statusTimer = setInterval(loadStatus, 5000);
}

function stopStatusPolling() {
  if (!statusTimer) return;
  clearInterval(statusTimer);
  statusTimer = null;
}

async function loadStatus() {
  if (!statusEls.taskBody) return;
  try {
    const response = await fetch("/api/status");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "读取运行总览失败。");
    renderStatus(payload);
  } catch (error) {
    statusEls.taskBody.innerHTML = `<tr class="empty-row"><td colspan="5">${escapeHtml(error.message)}</td></tr>`;
  }
}

function renderStatus(payload) {
  const summary = payload.summary || {};
  const recentTasks = payload.recentTasks || [];
  statusEls.generatedAt.textContent = payload.generatedAt || "--";
  statusEls.activeJobs.textContent = summary.activeJobs ?? 0;
  statusEls.latestRun.textContent = summary.latestRunAt || "--";
  statusEls.latestRunState.textContent = statusText(summary.latestRunStatus);
  statusEls.reportReady.textContent = summary.reportReadyRuns ?? 0;

  statusEls.taskBody.innerHTML = recentTasks.length
    ? recentTasks.map((task) => statusTaskRowHtml(task)).join("")
    : '<tr class="empty-row"><td colspan="5">暂无运行记录。</td></tr>';

  statusEls.taskBody.querySelectorAll(".status-report:not(:disabled)").forEach((button) => {
    button.addEventListener("click", () => {
      window.open(`/api/files/${encodeURIComponent(button.dataset.fileId)}/akquant_ha_report.html`, "_blank");
    });
  });
  statusEls.taskBody.querySelectorAll(".status-output:not(:disabled)").forEach((button) => {
    button.addEventListener("click", () => openStatusOutputDirectory(button.dataset.fileId, button));
  });

}

function statusTaskRowHtml(task) {
  const fileId = task.fileId || task.id || "";
  const reportDisabled = task.reportReady ? "" : "disabled";
  const outputDisabled = task.outputDir ? "" : "disabled";
  const progress = task.progress === null || task.progress === undefined ? "" : ` · ${task.progress}%`;
  return `
    <tr>
      <td><span class="status-chip ${statusClass(task.status)}">${statusText(task.status || task.statusText)}</span></td>
      <td>${escapeHtml(task.createdAt || "--")}</td>
      <td>
        <strong>${escapeHtml(statusStrategyName(task))}</strong>
        <small>${escapeHtml(task.startDate || "--")} 至 ${escapeHtml(task.endDate || "--")}</small>
      </td>
      <td>
        <div class="status-actions">
          <button class="report-link status-report" type="button" data-file-id="${escapeHtml(fileId)}" ${reportDisabled}>报告</button>
          <button class="report-link status-output" type="button" data-file-id="${escapeHtml(fileId)}" ${outputDisabled}>目录</button>
        </div>
      </td>
      <td><span class="status-log">${escapeHtml(task.message || task.step || "--")}${escapeHtml(progress)}</span></td>
    </tr>
  `;
}

async function openStatusOutputDirectory(fileId, button) {
  const originalText = button.textContent;
  try {
    button.textContent = "打开中";
    const response = await fetch(`/api/history/${encodeURIComponent(fileId)}/open-output-dir`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "打开输出目录失败。");
    button.textContent = "已请求";
    setTimeout(() => {
      button.textContent = originalText;
    }, 1200);
  } catch (error) {
    button.textContent = "失败";
    statusEls.generatedAt.textContent = error.message;
    setTimeout(() => {
      button.textContent = originalText;
    }, 1600);
  }
}

function statusStrategyName(item) {
  return strategies[item.strategy]?.title || item.strategyName || item.strategy || "未知策略";
}

function statusText(value) {
  const text = String(value || "").toLowerCase();
  const labels = {
    queued: "排队中",
    running: "执行中",
    completed: "已完成",
    failed: "失败",
    missing: "报告缺失",
    "missing report": "报告缺失",
    "no records": "暂无记录",
    "no historical runs": "暂无历史运行",
  };
  return labels[text] || value || "--";
}

function statusClass(value) {
  const text = String(value || "").toLowerCase();
  if (["running", "queued"].includes(text)) return "running";
  if (text === "completed") return "done";
  if (["failed", "missing", "missing report"].includes(text)) return "failed";
  return "idle";
}

const historyEls = {
  navButtons: Array.from(document.querySelectorAll('.view-switch button')),
  panels: Array.from(document.querySelectorAll('.view-panel')),
  strategyFilter: document.querySelector('#historyStrategyFilter'),
  durationMonthsFilter: document.querySelector('#historyDurationMonthsFilter'),
  totalReturnFilter: document.querySelector('#historyTotalReturnFilter'),
  annualizedReturnFilter: document.querySelector('#historyAnnualizedReturnFilter'),
  maxDrawdownFilter: document.querySelector('#historyMaxDrawdownFilter'),
  sharpeFilter: document.querySelector('#historySharpeFilter'),
  count: document.querySelector('#historyCount'),
  tableBody: document.querySelector('#historyTableBody'),
  detailStatus: document.querySelector('#historyDetailStatus'),
  detailTitle: document.querySelector('#historyDetailTitle'),
  detailRunId: document.querySelector('#detailRunId'),
  detailCreatedAt: document.querySelector('#detailCreatedAt'),
  detailPeriod: document.querySelector('#detailPeriod'),
  detailCash: document.querySelector('#detailCash'),
  detailFlags: document.querySelector('#detailFlags'),
  detailOutputDir: document.querySelector('#detailOutputDir'),
  openReport: document.querySelector('#openHistoryReport'),
  reuseParams: document.querySelector('#reuseHistoryParams'),
};

let selectedHistoryRunId = historyRuns[0]?.id || null;

function switchView(view) {
  historyEls.navButtons.forEach((button) => button.classList.toggle("active", button.dataset.viewTarget === view));
  historyEls.panels.forEach((panel) => panel.classList.toggle("hidden", panel.dataset.view !== view));
  if (view === "history") loadHistory();
  if (view === "status") startStatusPolling();
  else stopStatusPolling();
}

function syncHistoryStrategyOptions() {
  if (!historyEls.strategyFilter) return;
  const selected = historyEls.strategyFilter.value || "all";
  const strategyOptions = new Map();
  Object.entries(strategies).forEach(([id, item]) => strategyOptions.set(id, item.title));
  historyRuns.forEach((run) => strategyOptions.set(run.strategy, historyStrategyName(run)));
  historyEls.strategyFilter.innerHTML = [
    '<option value="all">\u5168\u90e8\u7b56\u7565</option>',
    ...Array.from(strategyOptions.entries()).map(([id, title]) => `<option value="${escapeHtml(id)}">${escapeHtml(title)}</option>`),
  ].join("");
  historyEls.strategyFilter.value = strategyOptions.has(selected) ? selected : "all";
}

async function loadHistory() {
  try {
    const response = await fetch("/api/history");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "\u8bfb\u53d6\u5386\u53f2\u56de\u6d4b\u5931\u8d25\u3002");
    historyRuns = (payload.runs || []).filter((run) => run.reportReady);
    if (!historyRuns.find((run) => run.id === selectedHistoryRunId)) selectedHistoryRunId = historyRuns[0]?.id || null;
  } catch (error) {
    historyRuns = [];
    selectedHistoryRunId = null;
    historyEls.detailStatus.textContent = "\u8bfb\u53d6\u5931\u8d25";
    historyEls.detailTitle.textContent = error.message;
  }
  syncHistoryStrategyOptions();
  renderHistory();
}

function getFilteredHistoryRuns() {
  const strategy = historyEls.strategyFilter.value;
  const minDurationMonths = parseHistoryFilterNumber(historyEls.durationMonthsFilter.value);
  const minTotalReturn = parseHistoryFilterNumber(historyEls.totalReturnFilter.value);
  const minAnnualizedReturn = parseHistoryFilterNumber(historyEls.annualizedReturnFilter.value);
  const maxDrawdown = parseHistoryFilterNumber(historyEls.maxDrawdownFilter.value);
  const minSharpe = parseHistoryFilterNumber(historyEls.sharpeFilter.value);

  return historyRuns.filter((run) => {
    if (!run.reportReady) return false;
    if (strategy !== 'all' && run.strategy !== strategy) return false;
    if (!passesDurationMonths(run, minDurationMonths)) return false;

    const metrics = run.reportMetrics || {};
    if (!passesMinimumMetric(metrics.totalReturn, minTotalReturn)) return false;
    if (!passesMinimumMetric(metrics.annualizedReturn, minAnnualizedReturn)) return false;
    if (!passesMaximumMetric(metrics.maxDrawdown, maxDrawdown)) return false;
    if (!passesMinimumMetric(metrics.sharpe, minSharpe)) return false;
    return true;
  });
}

function parseHistoryFilterNumber(value) {
  const text = String(value || '').trim();
  if (!text) return null;
  const number = Number(text);
  return Number.isNaN(number) ? null : number;
}

function parseHistoryMetric(value) {
  const text = String(value || '').replace(/,/g, '').replace(/%/g, '').trim();
  if (!text || text === '--') return null;
  const number = Number(text);
  return Number.isNaN(number) ? null : number;
}

function passesMinimumMetric(value, minimum) {
  if (minimum === null) return true;
  const metric = parseHistoryMetric(value);
  return metric !== null && metric >= minimum;
}

function passesMaximumMetric(value, maximum) {
  if (maximum === null) return true;
  const metric = parseHistoryMetric(value);
  return metric !== null && Math.abs(metric) <= maximum;
}

function passesDurationMonths(run, minimumMonths) {
  if (minimumMonths === null) return true;
  const durationMonths = historyDurationMonths(run.startDate, run.endDate);
  return durationMonths !== null && durationMonths >= minimumMonths;
}

function historyDurationMonths(startValue, endValue) {
  const start = new Date(normalizeHistoryDate(startValue));
  const end = new Date(normalizeHistoryDate(endValue));
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end < start) return null;
  return ((end - start) / 86400000 + 1) / 30.4375;
}

function normalizeHistoryDate(value) {
  return String(value || '').slice(0, 10);
}

function renderHistory() {
  if (!historyEls.tableBody) return;
  const rows = getFilteredHistoryRuns();
  historyEls.count.textContent = rows.length;
  if (!rows.find((run) => run.id === selectedHistoryRunId)) selectedHistoryRunId = rows[0]?.id || null;

  historyEls.tableBody.innerHTML = rows.length
    ? rows.map((run) => historyRowHtml(run)).join("")
    : '<tr class="empty-row"><td colspan="6">\u6ca1\u6709\u7b26\u5408\u5f53\u524d\u7b5b\u9009\u6761\u4ef6\u7684\u5386\u53f2\u6267\u884c\u8bb0\u5f55\u3002</td></tr>';

  historyEls.tableBody.querySelectorAll("tr[data-run-id]").forEach((row) => {
    row.addEventListener("click", () => {
      selectedHistoryRunId = row.dataset.runId;
      renderHistory();
    });
  });
  historyEls.tableBody.querySelectorAll(".report-link:not(:disabled)").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const run = historyRuns.find((item) => item.id === button.closest("tr").dataset.runId);
      if (run) window.open(historyReportUrl(run), "_blank");
    });
  });

  renderHistoryDetail(rows.find((run) => run.id === selectedHistoryRunId) || null);
}

function historyRowHtml(run) {
  const selected = run.id === selectedHistoryRunId ? ' selected' : '';
  const reportLabel = run.reportReady ? '\u67e5\u770b\u62a5\u544a' : '\u7f3a\u5931';
  const metrics = run.reportMetrics || {};
  return `
    <tr class='${selected}' data-run-id='${escapeHtml(run.id)}'>
      <td><button class='report-link' type='button' ${run.reportReady ? '' : 'disabled'}>${reportLabel}</button></td>
      <td class='history-run-cell'>
        <strong>${escapeHtml(historyStrategyName(run))}</strong>
        <small>${escapeHtml(run.startDate)} \u81f3 ${escapeHtml(run.endDate)}</small>
      </td>
      <td class='history-metric'>${escapeHtml(metrics.totalReturn || '--')}</td>
      <td class='history-metric'>${escapeHtml(metrics.annualizedReturn || '--')}</td>
      <td class='history-metric'>${escapeHtml(metrics.maxDrawdown || '--')}</td>
      <td class='history-metric'>${escapeHtml(metrics.sharpe || '--')}</td>
    </tr>
  `;
}

function renderHistoryDetail(run) {
  const hasRun = Boolean(run);
  const canReuse = hasRun && Boolean(strategies[run.strategy]);
  historyEls.detailStatus.textContent = hasRun ? (run.reportReady ? "\u62a5\u544a\u53ef\u7528" : "\u62a5\u544a\u7f3a\u5931") : "\u6682\u65e0\u8bb0\u5f55";
  historyEls.detailTitle.textContent = hasRun ? historyStrategyName(run) : "\u9009\u62e9\u4e00\u6761\u6267\u884c\u8bb0\u5f55";
  historyEls.detailRunId.textContent = hasRun ? run.id : "--";
  historyEls.detailCreatedAt.textContent = hasRun ? run.createdAt : "--";
  historyEls.detailPeriod.textContent = hasRun ? `${run.startDate} \u81f3 ${run.endDate}` : "--";
  historyEls.detailCash.textContent = hasRun ? formatMoney(run.initialCash) : "--";
  historyEls.detailFlags.textContent = hasRun ? formatFlags(run) : "--";
  historyEls.detailOutputDir.textContent = hasRun ? run.outputDir : "--";
  historyEls.openReport.disabled = !hasRun || !run.reportReady;
  historyEls.reuseParams.disabled = !canReuse;
  historyEls.openReport.onclick = hasRun && run.reportReady ? () => window.open(historyReportUrl(run), "_blank") : null;
  historyEls.reuseParams.onclick = canReuse ? () => reuseHistoryRun(run) : null;
}

function reuseHistoryRun(run) {
  if (!strategies[run.strategy]) return;
  els.strategySelect.value = run.strategy;
  els.startDate.value = run.startDate;
  els.endDate.value = run.endDate;
  els.initialCash.value = run.initialCash;
  els.refreshData.checked = run.refreshData;
  syncForm();
  switchView("run");
}

function historyStrategyName(run) {
  return strategies[run.strategy]?.title || run.strategyName || "\u672a\u77e5\u7b56\u7565";
}

function historyReportUrl(run) {
  return `/api/files/${encodeURIComponent(run.id)}/akquant_ha_report.html`;
}

function formatMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${Number(value).toLocaleString("zh-CN")} \u5143`;
}

function formatFlags(run) {
  return run.refreshData ? "\u5f3a\u5236\u5237\u65b0\u884c\u60c5" : "\u590d\u7528\u884c\u60c5\u7f13\u5b58";
}

historyEls.navButtons.forEach((button) => {
  button.addEventListener("click", () => switchView(button.dataset.viewTarget));
});

[
  historyEls.strategyFilter,
  historyEls.durationMonthsFilter,
  historyEls.totalReturnFilter,
  historyEls.annualizedReturnFilter,
  historyEls.maxDrawdownFilter,
  historyEls.sharpeFilter,
].forEach((control) => control.addEventListener("input", renderHistory));

initializeDefaultDates();
syncHistoryStrategyOptions();
renderHistory();
resetResult();
loadStrategies().then(loadHistory);
