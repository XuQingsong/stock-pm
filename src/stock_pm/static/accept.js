(() => {
  "use strict";

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);

  const pill = (text, cls = "") => `<span class="status-pill ${esc(cls)}">${esc(text)}</span>`;

  const gateValue = (value) => {
    if (value === true) return { label: "true", cls: "ok" };
    if (value === false) return { label: "false", cls: "not_configured" };
    return { label: "null · 尚无验收报告", cls: "not_configured" };
  };

  const verdictLine = (report) => {
    const verdict = (report && report.verdict) || {};
    const keys = Object.keys(verdict);
    if (!keys.length) return "尚无分项结果";
    return keys.map((key) => `${key}=${verdict[key]}`).join(" · ");
  };

  const render = (payload) => {
    const live = payload.live || {};
    const capability = payload.capability || {};
    const provider = gateValue(payload.provider_health_gate);
    const liveGate = gateValue(payload.live_e1_e10_gate);
    const capGate = gateValue(payload.capability_e1_e10_gate);
    const livePass = live.pass_count;
    const capPass = capability.pass_count;
    return `<div class="event-coverage-inner" data-accept-source="${esc(payload.source || "missing_accept_report")}" data-provider-health-gate="${payload.provider_health_gate === true ? "1" : "0"}" data-live-e1-e10-gate="${payload.live_e1_e10_gate === true ? "1" : payload.live_e1_e10_gate === false ? "0" : "null"}" data-capability-e1-e10-gate="${payload.capability_e1_e10_gate === true ? "1" : payload.capability_e1_e10_gate === false ? "0" : "null"}">
      <div class="accept-gates">
        <div class="gate-row" data-gate="provider_health">${pill(`provider_health_gate ${provider.label}`, provider.cls)}<span>来自机器可读报告，不是产品页文案。</span></div>
        <div class="gate-row" data-gate="live_e1_e10">${pill(`live_e1_e10_gate ${liveGate.label}`, liveGate.cls)}<span>live-current ${livePass == null ? "—" : livePass + "/10"}。UNOBSERVED 不计 PASS。</span></div>
        <div class="gate-row" data-gate="capability_e1_e10">${pill(`capability_e1_e10_gate ${capGate.label}`, capGate.cls)}<span>capability-black-box ${capPass == null ? "—" : capPass + "/10"}。E3 可为 UNVERIFIED。</span></div>
      </div>
      <div class="subline">live：${esc(verdictLine(live))}</div>
      <div class="subline">capability：${esc(verdictLine(capability))}</div>
      <div class="subline">${esc(payload.note || "精确 gate 只出现在本验收页和 JSON 报告。")}</div>
    </div>`;
  };

  async function load() {
    const root = document.getElementById("accept-report");
    if (!root) return;
    try {
      const response = await fetch("/api/accept/e1-e10", { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`请求失败（${response.status}）`);
      const payload = await response.json();
      root.innerHTML = render(payload);
      root.dataset.acceptReady = "1";
      root.dataset.eventsReady = "1";
    } catch (error) {
      root.innerHTML = `<b>验收报告不可用</b><span>${esc(error.message || "未知错误")}</span>`;
      root.dataset.acceptReady = "error";
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
