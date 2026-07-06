let strategies = {
  "ha-premium": {
    title: "H/A 溢价目标权重回测",
    command: "run",
    description: "每个交易日按 H/A 溢价排序，取前 10 只并根据 Top30 均值偏移分配仓位。",
  },
  "ha-premium-annual-line": {
    title: "H/A 溢价年线过滤回测",
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
  grossExposure: document.querySelector("#grossExposure"),
  grossExposureValue: document.querySelector("#grossExposureValue"),
  refreshData: document.querySelector("#refreshData"),
  integerPercent: document.querySelector("#integerPercent"),
  commandText: document.querySelector("#commandText"),
  copyCommand: document.querySelector("#copyCommand"),
  runButton: document.querySelector("#runButton"),
  pageTitle: document.querySelector("#pageTitle"),
  statusPill: document.querySelector("#statusPill"),
  sampleDays: document.querySelector("#sampleDays"),
  outputDir: document.querySelector("#outputDir"),
  reportState: document.querySelector("#reportState"),
  progressCaption: document.querySelector("#progressCaption"),
  progressPercent: document.querySelector("#progressPercent"),
  progressBar: document.querySelector("#progressBar"),
  steps: Array.from(document.querySelectorAll("#stepsList li")),
  premiumRows: document.querySelector("#premiumRows"),
  weightRows: document.querySelector("#weightRows"),
  positionCount: document.querySelector("#positionCount"),
  latestExposure: document.querySelector("#latestExposure"),
  weightsTable: document.querySelector("#weightsTable"),
  fileButtons: Array.from(document.querySelectorAll("#fileList button")),
  chartCaption: document.querySelector("#chartCaption"),
  canvas: document.querySelector("#equityChart"),
};

let pollTimer = null;
let currentJobId = null;

function toCliDate(value) {
  return value.replaceAll("-", "");
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
    ".\\.venv\\Scripts\\python.exe -m ha_backtest.cli",
    strategy.command,
    "--start",
    toCliDate(els.startDate.value),
    "--end",
    toCliDate(els.endDate.value),
  ];

  if (strategy.command === "run") {
    parts.push("--initial-cash", String(Number(els.initialCash.value || 0)));
  }

  parts.push("--gross-exposure", (Number(els.grossExposure.value) / 100).toFixed(2));

  if (els.refreshData.checked) parts.push("--refresh");
  if (els.integerPercent.checked) parts.push("--integer-percent");

  return parts.join(" ");
}

function syncForm() {
  const strategy = strategies[els.strategySelect.value] || Object.values(strategies)[0];
  if (!strategy) return;
  els.pageTitle.textContent = strategy.title;
  els.strategyMeta.textContent = strategy.description;
  els.grossExposureValue.textContent = `${els.grossExposure.value}%`;
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
  els.outputDir.textContent = "data/run_...";
  els.reportState.textContent = "未生成";
  els.premiumRows.textContent = "--";
  els.weightRows.textContent = "--";
  els.positionCount.textContent = "--";
  els.latestExposure.textContent = "--";
  els.chartCaption.textContent = "等待执行结果";
  els.weightsTable.innerHTML = emptyTableRow("执行完成后显示最新目标持仓。", 5);
  els.steps.forEach((step) => {
    step.className = "pending";
    step.querySelector("em").textContent = "等待";
  });
  els.fileButtons.forEach((button) => {
    button.disabled = true;
    button.classList.remove("ready");
    button.onclick = null;
  });
  drawChart([]);
}

function updateStep(progress, status) {
  const activeIndex = Math.min(4, Math.floor(progress / 20));
  els.steps.forEach((step, index) => {
    if (status === "failed") {
      step.className = index === activeIndex ? "active" : index < activeIndex ? "done" : "pending";
      step.querySelector("em").textContent = index === activeIndex ? "失败" : index < activeIndex ? "完成" : "等待";
    } else if (progress >= 100 || index < activeIndex) {
      step.className = "done";
      step.querySelector("em").textContent = "完成";
    } else if (index === activeIndex) {
      step.className = "active";
      step.querySelector("em").textContent = "执行中";
    } else {
      step.className = "pending";
      step.querySelector("em").textContent = "等待";
    }
  });
}

function requestPayload() {
  return {
    strategy: els.strategySelect.value,
    startDate: els.startDate.value,
    endDate: els.endDate.value,
    initialCash: Number(els.initialCash.value || 0),
    grossExposure: Number(els.grossExposure.value) / 100,
    refreshData: els.refreshData.checked,
    integerPercent: els.integerPercent.checked,
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
  if (job.output_dir) els.outputDir.textContent = job.output_dir;
  updateStep(progress, job.status);

  if (job.status === "queued" || job.status === "running") setStatus("running", "执行中");
  if (job.status === "completed") {
    setStatus("done", "已完成");
    renderResult(job);
  }
  if (job.status === "failed") setStatus("idle", "执行失败");
}

function renderResult(job) {
  const result = job.result || {};
  const metrics = result.metrics || {};
  els.outputDir.textContent = result.outputDir || job.output_dir || "--";
  els.reportState.textContent = hasFile(result, "akquant_ha_report.html") ? "已生成" : "未生成";
  els.premiumRows.textContent = formatNumber(metrics.premiumRows);
  els.weightRows.textContent = formatNumber(metrics.targetWeightRows);
  els.positionCount.textContent = formatNumber(metrics.positionCount);
  els.latestExposure.textContent = formatPercent(metrics.latestExposure);
  els.chartCaption.textContent = result.latestDate ? `截至 ${result.latestDate} 的每日目标仓位` : "本次任务无可展示曲线";
  renderWeights(result.weights || []);
  renderFiles(job.id, result.files || []);
  drawChart((result.exposureSeries || []).map((point) => point.value));
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

function renderFiles(jobId, files) {
  const byName = new Map(files.map((file) => [file.name, file.exists]));
  els.fileButtons.forEach((button) => {
    const filename = button.textContent.trim();
    const exists = byName.get(filename);
    button.disabled = !exists;
    button.classList.toggle("ready", Boolean(exists));
    button.onclick = exists ? () => window.open(`/api/files/${jobId}/${filename}`, "_blank") : null;
  });
}

function hasFile(result, filename) {
  return Boolean((result.files || []).find((file) => file.name === filename && file.exists));
}

function drawChart(series) {
  const canvas = els.canvas;
  const context = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const pad = 28;

  context.clearRect(0, 0, width, height);
  context.fillStyle = "#f8fafc";
  context.fillRect(0, 0, width, height);
  context.strokeStyle = "#d9e0e8";
  context.lineWidth = 1;

  for (let i = 0; i < 5; i += 1) {
    const y = pad + ((height - pad * 2) / 4) * i;
    context.beginPath();
    context.moveTo(pad, y);
    context.lineTo(width - pad, y);
    context.stroke();
  }

  if (!series.length) {
    context.fillStyle = "#667085";
    context.font = "16px Microsoft YaHei, Arial";
    context.textAlign = "center";
    context.fillText("执行完成后显示每日目标仓位", width / 2, height / 2);
    return;
  }

  const min = Math.min(0, ...series) * 0.98;
  const max = Math.max(1, ...series) * 1.02;
  const toX = (index) => pad + ((width - pad * 2) * index) / Math.max(1, series.length - 1);
  const toY = (value) => height - pad - ((height - pad * 2) * (value - min)) / (max - min || 1);

  context.beginPath();
  series.forEach((value, index) => {
    const x = toX(index);
    const y = toY(value);
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  context.strokeStyle = "#11685f";
  context.lineWidth = 4;
  context.stroke();

  const lastX = toX(series.length - 1);
  const lastY = toY(series.at(-1));
  context.fillStyle = "#11685f";
  context.beginPath();
  context.arc(lastX, lastY, 6, 0, Math.PI * 2);
  context.fill();
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
        title: item.name,
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
  els.grossExposure,
  els.refreshData,
  els.integerPercent,
].forEach((control) => control.addEventListener("input", syncForm));

els.copyCommand.addEventListener("click", async () => {
  await navigator.clipboard.writeText(els.commandText.textContent);
  els.copyCommand.textContent = "✓";
  setTimeout(() => {
    els.copyCommand.textContent = "⧉";
  }, 900);
});

els.runButton.addEventListener("click", startRun);

resetResult();
loadStrategies();
