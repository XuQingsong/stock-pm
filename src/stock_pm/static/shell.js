(() => {
  "use strict";

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);

  const FLAG_LABELS = { options: "期权概览", macro: "宏观", reviews: "复盘", environment: "环境半句" };

  async function mountStockPmShell(options) {
    const host = document.getElementById("stock-pm-shell");
    if (!host) return null;
    const params = new URLSearchParams();
    if (options && options.date) params.set("date", options.date);
    if (options && options.symbol) params.set("symbol", options.symbol);
    const query = params.toString();
    const response = await fetch(`/api/shell${query ? `?${query}` : ""}`, {
      headers: { Accept: "application/json" }
    });
    if (!response.ok) {
      host.innerHTML = "";
      return null;
    }
    const data = await response.json();
    const alerts = (data.alerts || []).filter((item) => item.severity === "severe");
    const state = data.explicit_state || {};
    const env = data.environment || {};
    const flags = env.missingFlags || [];
    const thesis = options && options.symbol ? (env.row_thesis || env.one_liner) : env.one_liner;
    const alertHtml = alerts.length
      ? `<div class="alert-strip visible" role="alert">${alerts.map((item) =>
        `<div class="alert-item"><b>${esc(item.title || "严重提醒")}</b><span>${esc(item.message || "")}</span></div>`
      ).join("")}</div>`
      : "";
    const flagText = flags.length
      ? `数据暂缺：${flags.map((flag) => FLAG_LABELS[flag] || flag).join("、")}`
      : "";
    host.innerHTML = `${alertHtml}
      <section class="zone zone-a" data-zone="A">
        <div class="zone-label">结论</div>
        <div class="state-row">
          <span class="state-chip ${esc(state.code || "missing")}">${esc(state.label || "数据暂缺")}</span>
          <span class="env-meta">${esc(state.detail || "")}</span>
        </div>
        <p class="env-line">${esc(thesis || "隔夜环境半句暂缺。")}</p>
        <div class="env-meta">${esc(env.publishState ? `发布态 ${env.publishState}` : "")}${env.prediction_ready ? "" : " · 预测状态机尚未接入"}</div>
        ${flagText ? `<div class="missing-flags">${esc(flagText)}</div>` : ""}
      </section>`;
    return data;
  }

  window.mountStockPmShell = mountStockPmShell;
})();
