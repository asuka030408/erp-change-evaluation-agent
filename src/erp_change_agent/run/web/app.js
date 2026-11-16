/* Browser behavior for the loopback-only UI. All report text enters the DOM as textContent. */
const $ = (id) => document.getElementById(id);
let bootstrap = null;
let current = null;

function notice(message, kind = "info") {
  const box = $("notice");
  box.textContent = message;
  box.className = `notice ${kind}`;
}
function clearNotice() { $("notice").className = "notice hidden"; }

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  if (options.method && options.method !== "GET") headers["X-Local-UI-Token"] = bootstrap.write_token;
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "请求失败，请检查输入后重试。";
    throw new Error(detail);
  }
  return data;
}

function setWorking(working) {
  $("submit-btn").disabled = working || !bootstrap?.model_ready;
  $("submit-btn").querySelector("span").textContent = working ? "正在查证资料…" : "开始评估";
  $("tenant").disabled = working;
  $("request").disabled = working;
}

function plainMarkdown(text) { return text.replace(/\*\*|`/g, ""); }
function renderMarkdown(markdown) {
  const target = $("report-body");
  target.replaceChildren();
  let list = null;
  for (const raw of markdown.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) { list = null; continue; }
    let element;
    if (line.startsWith("## ")) { element = document.createElement("h2"); element.textContent = line.slice(3); list = null; }
    else if (line.startsWith("# ")) { element = document.createElement("h1"); element.textContent = line.slice(2); list = null; }
    else if (line.startsWith("- ")) {
      if (!list) { list = document.createElement("ul"); target.append(list); }
      element = document.createElement("li");
      element.textContent = plainMarkdown(line.slice(2));
      list.append(element);
      continue;
    } else { element = document.createElement("p"); element.textContent = plainMarkdown(line); list = null; }
    target.append(element);
  }
}

function showReport(data) {
  current = data;
  $("empty-result").classList.add("hidden");
  $("report-panel").classList.remove("hidden");
  $("run-id").textContent = data.run_id;
  $("result-status").textContent = data.status === "awaiting_review" ? "等待人工审阅" : "已完成审阅";
  $("result-status").className = `status-pill ${data.status === "awaiting_review" ? "pending" : "done"}`;
  const usage = data.model_usage;
  $("usage").textContent = usage?.calls ? `本次模型调用 ${usage.calls} 次 · 输入 ${usage.input_tokens ?? 0} tokens · 输出 ${usage.output_tokens ?? 0} tokens` : "";
  renderMarkdown(data.report || "暂无报告正文");
  $("review-panel").classList.toggle("hidden", data.status !== "awaiting_review");
  $("reviewed-message").classList.toggle("hidden", data.status === "awaiting_review");
  if (data.review) {
    $("reviewed-message").textContent = `${data.review.reviewer} 已${data.review.decision === "approve" ? "审核通过" : "驳回"}这份报告。报告审核不授权生产修改。`;
  }
  history.replaceState(null, "", `?run=${encodeURIComponent(data.run_id)}&tenant=${encodeURIComponent(data.tenant_id)}`);
  $("result").scrollIntoView({ behavior: "auto", block: "start" });
}

function fillExample(kind) {
  const th = $("tenant").value === "TENANT-TH";
  const examples = th ? {
    threshold: "天衡：普通采购恰好 50,000 元要走几级审批？请引用现行合同和配置。",
    interface: "天衡：如果修改普通采购审批规则，现有资料能确认哪些影响？还缺哪些信息？",
    deployment: "天衡：业务负责人同意了，现在就能部署吗？请列出尚需确认的条件。",
  } : {
    threshold: "星河：请评估把普通采购三级审批阈值从 100,000 元改为 50,000 元的影响；现在哪些决定生效？",
    interface: "星河：阈值从 100,000 元降到 50,000 元，订单接口需要改吗？请区分接口字段和回归测试。",
    deployment: "星河：业务负责人同意了，现在就能部署吗？请列出尚需确认的条件。",
  };
  $("request").value = examples[kind] || "";
  $("request").dispatchEvent(new Event("input"));
  $("request").focus();
}

async function openReport(runId, tenantId) {
  const data = await api(`/ui/assessments/${encodeURIComponent(runId)}?tenant_id=${encodeURIComponent(tenantId)}`);
  showReport(data);
}

async function review(decision) {
  if (!current) return;
  const reviewer = $("reviewer").value.trim();
  if (!reviewer) { notice("请先填写审阅人姓名。", "error"); $("reviewer").focus(); return; }
  $("approve-btn").disabled = $("reject-btn").disabled = true;
  try {
    const result = await api(`/ui/assessments/${encodeURIComponent(current.run_id)}/review`, {
      method: "POST", body: JSON.stringify({ tenant_id: current.tenant_id, reviewer,
        note: $("review-note").value.trim(), decision }),
    });
    current.status = "reviewed";
    current.review = result.review;
    showReport(current);
    notice("审阅记录已保存。它不授权生产变更。", "success");
  } catch (error) { notice(error.message, "error"); }
  finally { $("approve-btn").disabled = $("reject-btn").disabled = false; }
}

async function init() {
  try {
    bootstrap = await api("/ui/bootstrap");
    $("mode-pill").textContent = bootstrap.mode === "demo" ? "演示资料 · 虚构租户" : "正式资料 · 本机";
    $("source-caption").textContent = `${bootstrap.mode === "demo" ? "正在使用虚构测试资料" : "正在使用正式资料"} · ${bootstrap.source_path}`;
    $("tenant").replaceChildren();
    for (const tenant of bootstrap.tenants) {
      const option = document.createElement("option"); option.value = tenant;
      option.textContent = tenant === "TENANT-XH" ? "星河 · TENANT-XH" : tenant === "TENANT-TH" ? "天衡 · TENANT-TH" : tenant;
      $("tenant").append(option);
    }
    if (bootstrap.tenants.includes("TENANT-XH")) $("tenant").value = "TENANT-XH";
    if (!bootstrap.tenants.length) notice("当前没有可用资料。请先导入文件，再打开工作台。", "error");
    if (!bootstrap.model_ready) notice("尚未配置 DeepSeek API 密钥。请关闭服务，用启动脚本重新打开。", "error");
    setWorking(false);
    const params = new URLSearchParams(location.search);
    if (params.get("run") && params.get("tenant")) {
      $("tenant").value = params.get("tenant");
      await openReport(params.get("run"), params.get("tenant"));
    }
  } catch (error) { notice(`页面初始化失败：${error.message}`, "error"); }
}

$("request").addEventListener("input", () => { $("char-count").textContent = `${$("request").value.length} / 10000`; });
for (const button of document.querySelectorAll("[data-example]")) button.addEventListener("click", () => fillExample(button.dataset.example));
$("assessment-form").addEventListener("submit", async (event) => {
  event.preventDefault(); clearNotice();
  const request = $("request").value.trim(); const tenant_id = $("tenant").value;
  if (!request || !tenant_id) { notice("请选择客户并填写需求。", "error"); return; }
  setWorking(true); notice("正在读取资料、形成初步评估并核对引用。通常需要几十秒，请不要关闭页面。", "info");
  try {
    const data = await api("/ui/assessments", { method: "POST", body: JSON.stringify({ tenant_id, request }) });
    showReport(data); notice("评估草稿已生成，等待人工审阅。", "success");
  } catch (error) { notice(`评估失败：${error.message}`, "error"); }
  finally { setWorking(false); }
});
$("lookup-btn").addEventListener("click", async () => {
  const run = $("lookup-id").value.trim();
  if (!run) { notice("请输入任务编号。", "error"); return; }
  try { await openReport(run, $("tenant").value); clearNotice(); }
  catch (error) { notice(error.message, "error"); }
});
$("copy-id").addEventListener("click", async () => { if (current) { await navigator.clipboard.writeText(current.run_id); notice("任务编号已复制。", "success"); } });
$("download-report").addEventListener("click", () => {
  if (!current) return;
  const url = URL.createObjectURL(new Blob([current.report], { type: "text/markdown;charset=utf-8" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = `ERP评估_${current.run_id}.md`;
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$("approve-btn").addEventListener("click", () => review("approve"));
$("reject-btn").addEventListener("click", () => review("reject"));
init();
