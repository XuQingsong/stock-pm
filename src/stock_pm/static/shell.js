(() => {
  "use strict";

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);

  const FLAG_LABELS = {
    options: "期权概览",
    macro: "宏观",
    reviews: "复盘",
    environment: "环境半句",
    "fundamentals.year_move": "一年涨跌",
    "fundamentals.earnings": "财报对照",
    "fundamentals.industry": "行业增长",
    "fundamentals.valuation": "估值",
    "news.macro": "宏观消息",
    "news.sector": "行业消息",
    "news.company": "公司消息",
    sentiment: "情绪氛围"
  };

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
    const thesis = options && options.symbol
      ? (env.conflict ? (env.row_thesis || env.one_liner) : (env.synthesis || env.one_liner || env.row_thesis))
      : env.one_liner;
    const alertHtml = alerts.length
      ? `<div class="alert-strip visible" role="alert">${alerts.map((item) =>
        `<div class="alert-item"><b>${esc(item.title || "严重提醒")}</b><span>${esc(item.message || "")}</span></div>`
      ).join("")}</div>`
      : "";
    const flagText = flags.length
      ? `数据暂缺：${flags.map((flag) => FLAG_LABELS[flag] || flag).join("、")}`
      : "";
    const bullets = ((env.struct || {}).bullets) || [];
    const zoneB = (options && options.symbol)
      ? `<section class="zone zone-b" data-zone="B">
        <div class="zone-label">展开</div>
        <ul class="env-bullets">${(bullets.length ? bullets : [
          { title: "基本面", clause: "结构化要点暂缺" },
          { title: "消息面", clause: "结构化要点暂缺" },
          { title: "情绪面", clause: "结构化要点暂缺" }
        ]).map((item) =>
          `<li class="${item.missing ? "missing" : ""}"><b>${esc(item.title)}</b> ${esc(item.clause)}<span class="points-to">→ 支撑结论</span></li>`
        ).join("")}</ul>
      </section>
      <details class="fold zone-c" data-zone="C">
        <summary>折叠材料（财报 / 估值 / 资讯原接口，不在结论区铺开）</summary>
        <p>数字与原文仍走既有接口：<a href="#earnings">财报</a> · <a href="#valuation">估值</a> · <a href="#news-options">资讯与期权</a>。这里不堆标题墙。</p>
      </details>`
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
      </section>${zoneB}`;
    return data;
  }

  window.mountStockPmShell = mountStockPmShell;
})();
