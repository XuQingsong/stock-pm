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
    options: "缺期权",
    macro: "缺宏观",
    reviews: "缺复盘",
    environment: "缺环境",
    "fundamentals.year_move": "缺一年涨跌",
    "fundamentals.earnings": "缺财报对照",
    "fundamentals.industry": "缺行业增长",
    "fundamentals.valuation": "缺估值",
    "news.macro": "缺宏观消息",
    "news.sector": "缺行业消息",
    "news.company": "缺可映射新闻",
    sentiment: "缺情绪氛围",
    volume_price: "缺量价形态",
    chips: "缺筹码与支撑压力",
    break: "缺破位走法",
    env_link: "缺对照行情",
    weak_vs_env: "缺弱于环境判定",
    tape: "缺昨盘",
    review_note: "缺复盘总结",
    entry_price: "缺入场价",
    support: "缺下沿",
    resistance: "缺上沿",
    window: "缺时间窗",
    price: "缺对照行情",
    decision_direction: "决策方向"
  };

  const PUBLISH_LABELS = {
    published: "结论已生成",
    draft: "草稿待补",
    stale: "结论已过期",
    missing: "本条未产出"
  };

  const STATE_LABELS = {
    auto_gen: "已自动生成",
    pending: "待生效",
    active: "跟踪中",
    hit: "已兑现",
    invalidated: "已打脸",
    superseded: "已改口",
    missing: "到期未产出"
  };

  function missingFlagText(flags) {
    const list = (flags || []).map((flag) => FLAG_LABELS[flag] || `缺${flag}`);
    return list.length ? list.join("、") : "";
  }

  function predictionDisplay(pred) {
    if (pred && (pred.direction_withheld || pred.can_form_direction === false || pred.state === "withheld")) {
      return pred.therefore || pred.missing_label || "决策未形成方向，不展示百分比预测";
    }
    if (!pred || pred.state === "missing" || !pred.prediction_ready) {
      const named = missingFlagText(pred && pred.missingFlags);
      return (pred && (pred.missing_label || pred.therefore)) || (named ? `${named}，未编造时间窗口或涨跌边界。` : "到期未产出");
    }
    if (pred.therefore) return pred.therefore;
    const window = pred.window_label || "窗口";
    if (pred.upside_bound_pct != null && pred.downside_bound_pct != null) {
      return `因此：${window} 上${_escPct(pred.upside_bound_pct)} / 下${_escPct(pred.downside_bound_pct)}`;
    }
    return pred.badge || pred.one_liner || "到期未产出";
  }

  function predictionTone(pred) {
    if (!pred) return "missing";
    if (pred.state === "invalidated") return "slap";
    if (pred.judgment_alert && pred.judgment_alert.severity === "severe") return "severe";
    if (pred.state === "missing" || !pred.prediction_ready || ((pred.missingFlags || []).length)) return "missing";
    if (pred.state === "hit") return "up";
    return "";
  }

  function predictionCard(pred, options) {
    const ready = pred && pred.prediction_ready && pred.state !== "missing";
    const flags = (pred && pred.missingFlags) || [];
    const flagText = flags.length ? missingFlagText(flags) : "";
    const state = pred && pred.state;
    const alert = pred && pred.judgment_alert;
    const slap = !!(
      ready && state === "invalidated"
      && alert && alert.id && alert.severity === "severe"
    );
    const cta = slap
      ? `<div class="judgment-change">
          <p>打脸已写入。须严重提醒后改口并写原因。</p>
          <textarea class="change-reason" placeholder="改口原因（必填）"></textarea>
          <button type="button" class="btn supersede-btn" data-prediction-id="${esc(pred.id || "")}" data-symbol="${esc((options && options.symbol) || pred.symbol || "")}" data-alert-id="${esc(alert.id)}">改口并写原因</button>
          <span class="muted supersede-status"></span>
        </div>`
      : "";
    const tone = predictionTone(pred);
    return `<div class="prediction-card ${ready ? "ready" : "missing"} tone-${tone || "rest"}">
      <div class="zone-label">预测</div>
      <p class="env-line tone-a ${tone ? `tone-${tone}` : ""}">${esc(predictionDisplay(pred))}</p>
      <div class="env-meta">${esc(STATE_LABELS[state] || "到期未产出")}</div>
      ${ready ? `<a class="pred-basis" href="#zone-tape">依据↑环境/昨盘</a>` : ""}
      ${flagText ? `<div class="missing-flags">${esc(flagText)}</div>` : ""}
      ${cta}
    </div>`;
  }

  function newsHref(item) {
    const url = item && item.url;
    try {
      const parsed = new URL(String(url), location.origin);
      return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
    } catch (_) {
      return "";
    }
  }

  function newsStanceLine(item) {
    if (item && item.stance_line) return item.stance_line;
    const impacts = (item && item.impacts) || [];
    const dirs = impacts.map((impact) => String(impact.direction || ""));
    const bull = dirs.some((d) => d.includes("多") || d.includes("好"));
    const bear = dirs.some((d) => d.includes("空"));
    let stance = "分歧";
    if (bull && !bear) stance = "利好";
    else if (bear && !bull) stance = "利空";
    const because = (impacts.find((impact) => impact.rationale) || {}).rationale
      || (item && item.summary)
      || "规则未映射到可核对依据";
    return `${stance} · 因为${because}`;
  }

  function newsHeadline(item) {
    const href = newsHref(item);
    const title = esc((item && item.headline) || "无标题");
    if (href) {
      return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${title}</a>`;
    }
    return `<b>${title}</b> <span class="no-url">无原文链接</span>`;
  }

  function newsBlock(item) {
    return `<article class="news-item">${newsHeadline(item)}<div class="news-stance">${esc(newsStanceLine(item))}</div></article>`;
  }

  function publishMeta(state, suffix) {
    const label = PUBLISH_LABELS[state] || "";
    if (!label) return suffix || "";
    if (state === "published") return suffix || "";
    return suffix ? `${label} · ${suffix}` : label;
  }

  function _escPct(value) {
    if (value === null || value === undefined) return "—";
    const n = Number(value);
    return `${n > 0 ? "+" : ""}${n}%`;
  }

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
        `<div class="alert-item"><b>${esc(item.title || "严重提醒")}</b><span>${esc(item.message || "")}</span>${item.cta === "judgment_change" && item.id ? `<div class="env-meta">改口在个股预测区。须严重提醒后改口并写原因。</div>` : (item.legacy ? `<div class="env-meta">规则对照，不是时间窗口或涨跌边界。</div>` : "")}</div>`
      ).join("")}</div>`
      : "";
    const flagText = flags.length ? missingFlagText(flags) : "";
    const bullets = ((env.struct || {}).bullets) || [];
    const tape = data.tape || {};
    const note = data.review_note || {};
    const tapeAnswers = ((tape.struct || {}).answers) || {};
    const tapeFlags = tape.missingFlags || [];
    const tapeFlagText = tapeFlags.length ? missingFlagText(tapeFlags) : "";
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
      <section class="zone zone-tape" id="zone-tape" data-zone="tape">
        <div class="zone-label">昨盘</div>
        <p class="env-line">${esc(tape.one_liner || "昨盘结论未就绪")}</p>
        <div class="env-meta">${esc(publishMeta(tape.publishState, "昨盘不是预测"))}</div>
        ${tapeFlagText ? `<div class="missing-flags">${esc(tapeFlagText)}</div>` : ""}
        <ul class="env-bullets">${tapeItems.map((item) =>
          `<li class="${item.missing ? "missing" : ""}"><b>${esc(item.title)}</b> ${esc(item.clause)}</li>`
        ).join("")}</ul>
      </section>
      <section class="zone zone-review" data-zone="review">
        <div class="zone-label">复盘与预测</div>
        ${(note.summary && note.summary !== tape.one_liner) ? `<p class="env-line">${esc(note.summary)}</p>` : ""}
        <p class="review-explain">${esc(note.explanation || "解释不了：消息与情绪依据不足，不硬编诱多、转势、吸筹或逃跑。")}</p>
        ${note.unexplained ? `<div class="missing-flags">解释不了</div>` : ""}
        ${predictionCard(data.prediction, options)}
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
        <p class="env-line tone-a ${esc(state.code === "face_slap" ? "tone-slap" : state.code === "overdue" ? "tone-overdue" : state.code === "missing" ? "tone-missing" : "")}">${esc(thesis || "隔夜环境半句暂缺。")}</p>
        <div class="env-meta">${esc(publishMeta(env.publishState, "环境不是预测"))}</div>
        ${flagText ? `<div class="missing-flags">${esc(flagText)}</div>` : ""}
      </section>${zoneB}`;
    host.querySelectorAll(".supersede-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const wrap = btn.closest(".judgment-change");
        const reason = wrap ? wrap.querySelector(".change-reason").value : "";
        const status = wrap ? wrap.querySelector(".supersede-status") : null;
        if (status) status.textContent = "提交中…";
        try {
          const response = await fetch(
            `/api/stock/${encodeURIComponent(btn.dataset.symbol)}/predictions/${encodeURIComponent(btn.dataset.predictionId)}/supersede`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json", Accept: "application/json" },
              body: JSON.stringify({
                change_reason: reason,
                alert_id: Number(btn.dataset.alertId)
              })
            }
          );
          const body = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(body.detail || "改口失败");
          if (status) status.textContent = "已留痕";
          mountStockPmShell(options);
        } catch (error) {
          if (status) status.textContent = error.message || "改口失败";
        }
      });
    });
    return data;
  }

  window.mountStockPmShell = mountStockPmShell;
  window.stockPmCopy = {
    esc,
    FLAG_LABELS,
    missingFlagText,
    predictionDisplay,
    predictionTone,
    newsHref,
    newsStanceLine,
    newsHeadline,
    newsBlock,
    publishMeta
  };
})();
