(() => {
  "use strict";

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);

  function weakVsEnvDisplay(weak, fallbackClause) {
    const row = weak || {};
    const bench = row.benchmark || "暂缺";
    const rel = row.prior_relative_return_pct;
    const relText = (rel === null || rel === undefined) ? "暂缺" : `${Number(rel) > 0 ? "+" : ""}${rel}%`;
    const path = row.structure_or_volume_down;
    const pathText = path === true ? "是" : path === false ? "否" : "暂缺";
    let conc = "无法判定";
    if (row.status === "weak") conc = "弱于环境";
    else if (row.status === "not_weak") conc = "并非弱于环境";
    const facts = `基准 ${bench} · 昨收相对 ${relText} · 破位或放量跌 ${pathText} · 结论 ${conc}`;
    const clause = row.clause || fallbackClause || "相对收益或破位路径暂缺，无法判定弱于环境，不编造偏弱。";
    return `${clause} ${facts}`;
  }

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
    sentiment: "情绪氛围",
    volume_price: "量价形态",
    chips: "筹码与支撑压力",
    break: "破位走法",
    env_link: "环境对照",
    weak_vs_env: "弱于环境",
    tape: "昨盘",
    review_note: "复盘总结"
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
    const tape = data.tape || {};
    const note = data.review_note || {};
    const tapeAnswers = ((tape.struct || {}).answers) || {};
    const tapeFlags = tape.missingFlags || [];
    const tapeFlagText = tapeFlags.length
      ? `数据暂缺：${tapeFlags.map((flag) => FLAG_LABELS[flag] || flag).join("、")}`
      : "";
    const tapeItems = [
      { title: "量价形态", clause: tapeAnswers.q1_volume_price || (tape.volume_price && tape.volume_price.clause) || "量价形态暂缺，不编放量缩量" },
      { title: "筹码与支撑压力", clause: tapeAnswers.q2_chips || (tape.chips && tape.chips.clause) || "筹码带与支撑压力暂缺，不编价位" },
      { title: "破位走法", clause: tapeAnswers.q3_break || (tape.break && tape.break.clause) || "破位走法暂缺，不编拉回续杀" },
      { title: "对照环境", clause: tapeAnswers.q4_env_link || (tape.env_link && tape.env_link.clause) || "环境依据不足，不编诱多/转势/吸筹/逃跑" },
      { title: "弱于环境", clause: weakVsEnvDisplay(tape.weak_vs_env, tapeAnswers.q5_weak_vs_env), missing: tapeFlags.indexOf("weak_vs_env") >= 0 || (tape.weak_vs_env && tape.weak_vs_env.status === "missing") }
    ];
    const zoneB = (options && options.symbol)
      ? `<section class="zone zone-b" data-zone="B">
        <div class="zone-label">展开 · 环境</div>
        <ul class="env-bullets">${(bullets.length ? bullets : [
          { title: "基本面", clause: "结构化要点暂缺" },
          { title: "消息面", clause: "结构化要点暂缺" },
          { title: "情绪面", clause: "结构化要点暂缺" }
        ]).map((item) =>
          `<li class="${item.missing ? "missing" : ""}"><b>${esc(item.title)}</b> ${esc(item.clause)}<span class="points-to">→ 支撑结论</span></li>`
        ).join("")}</ul>
      </section>
      <section class="zone zone-tape" data-zone="tape">
        <div class="zone-label">昨盘</div>
        <p class="env-line">${esc(tape.one_liner || "昨盘结论未就绪（M2）")}</p>
        <div class="env-meta">${esc(tape.publishState ? `发布态 ${tape.publishState}` : "")}${tape.prediction_ready ? "" : " · 不编预测边界"}</div>
        ${tapeFlagText ? `<div class="missing-flags">${esc(tapeFlagText)}</div>` : ""}
        <ul class="env-bullets">${tapeItems.map((item) =>
          `<li class="${item.missing ? "missing" : ""}"><b>${esc(item.title)}</b> ${esc(item.clause)}</li>`
        ).join("")}</ul>
      </section>
      <section class="zone zone-review" data-zone="review">
        <div class="zone-label">复盘与预测</div>
        <p class="env-line">${esc(note.summary || "复盘总结暂缺，不编白话。")}</p>
        <p class="review-explain">${esc(note.explanation || "解释不了：消息与情绪依据不足，不硬编诱多、转势、吸筹或逃跑。")}</p>
        ${note.unexplained ? `<div class="missing-flags">解释不了</div>` : ""}
        <div class="prediction-placeholder">预测状态机尚未接入，不编时间窗口或涨跌边界。</div>
      </section>
      <details class="fold zone-c" data-zone="C">
        <summary>折叠材料（K 线 MA5/20/50/200 / 财报 / 估值 / 资讯原接口，不在结论区铺开）</summary>
        <p>图表与数字仍走既有接口：<a href="#chart">K 线与均线</a> · <a href="#flow">筹码与资金</a> · <a href="#earnings">财报</a> · <a href="#valuation">估值</a> · <a href="#news-options">资讯与期权</a>。材料不能代替昨盘结论。</p>
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
