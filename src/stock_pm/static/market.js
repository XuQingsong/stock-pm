(() => {
  "use strict";

  const OVERVIEW_PATH = "/api/market/overview";
  const EMPTY_DOMINANT = "当前尚未形成明确主导变量";
  const ROLE_CLASS = { 主导: "primary", 次主导: "secondary", 辅助: "assist" };
  const IMPORTANCE_ZH = { very_high: "很高", high: "高", medium: "中", low: "低" };
  const CONFIDENCE_ZH = { high: "高", medium: "中", low: "低" };
  const TREND_ZH = {
    strengthening: "正在增强",
    stable: "高位持续",
    weakening: "影响减弱",
    fading: "基本消退",
  };
  const STATUS_ZH = { active: "持续中", watching: "观察中", resolved: "已消退" };
  const DIRECTION_ZH = { up: "上行", down: "下行", mixed: "方向分化" };

  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[ch]);

  const hasCjk = (value) => /[\u4e00-\u9fff]/.test(String(value || ""));
  const looksLikeId = (value) =>
    /^(gmdd_|bev_|bclm_|att_|bdrv_|bexp_|bobs_)/i.test(String(value || "").trim());

  function displayText(value, fallback) {
    const raw = String(value || "").trim();
    if (!raw || looksLikeId(raw)) return fallback || "";
    return raw;
  }

  function zhMap(table, raw, fallback) {
    const key = String(raw || "").trim().toLowerCase();
    if (table[key]) return table[key];
    if (hasCjk(raw)) return String(raw);
    return fallback || "";
  }

  function chip(label, klass) {
    if (!label) return "";
    return `<span class="chip ${klass}">${esc(label)}</span>`;
  }

  function listBlock(title, klass, items) {
    const rows = (items || []).map((item) => displayText(item.label || item.title || item, "")).filter(Boolean);
    if (!rows.length) {
      return `<div class="signal-block ${klass}"><h4>${esc(title)}</h4><p class="muted-empty">暂无已记录条目</p></div>`;
    }
    return `<div class="signal-block ${klass}"><h4>${esc(title)}</h4><ul>${rows
      .map((row) => `<li>${esc(row)}</li>`)
      .join("")}</ul></div>`;
  }

  function formatAsOf(stamp) {
    const raw = String(stamp || "").trim();
    const match = raw.match(/(\d{4})-(\d{2})-(\d{2})/);
    if (!match) return "数据时间暂缺";
    return `数据截至 ${match[2]}-${match[3]}`;
  }

  function relatedTickers(data) {
    const fromDrivers = (data.dominant_drivers || []).flatMap((row) => row.affected_tickers || []);
    const seen = new Set();
    const out = [];
    for (const token of fromDrivers) {
      const symbol = String(token || "").toUpperCase();
      if (!symbol || seen.has(symbol)) continue;
      seen.add(symbol);
      out.push(symbol);
    }
    return out;
  }

  function axisRows(axis) {
    if (!axis.length) return "";
    return `<div class="axis-rows">${axis
      .map((row) => {
        const role = displayText(row.role, "");
        const name = displayText(row.name, "");
        if (!role || !name) return "";
        const klass = ROLE_CLASS[role] || "assist";
        return `<div class="axis-row ${klass}"><span class="role">${esc(role)}</span><span class="name">${esc(
          name
        )}</span></div>`;
      })
      .join("")}</div>`;
  }

  function statusChips(data, drivers) {
    if (!drivers.length) return "";
    const top = drivers[0] || {};
    const chips = [];
    chips.push(chip("主轴清晰", "status-ok"));
    const cred = zhMap(CONFIDENCE_ZH, top.confidence, "");
    if (cred) chips.push(chip(`可信度 ${cred}`, cred === "低" ? "cred-low" : "cred-mid"));
    const triggers = data.trigger_events || [];
    if (triggers.length) chips.push(chip("近窗有触发", "status-watch"));
    if (drivers.length >= 2) chips.push(chip("多解释并存", "tag-multi"));
    return `<div class="status-meta">${chips.join("")}</div>`;
  }

  function driverCard(row, index) {
    const name = displayText(row.display_name || row.name, "");
    if (!name) return "";
    const importance = zhMap(IMPORTANCE_ZH, row.importance, "");
    const confidence = zhMap(CONFIDENCE_ZH, row.confidence, "");
    const trend = zhMap(TREND_ZH, row.trend, "");
    const status = zhMap(STATUS_ZH, row.status, "");
    const direction = zhMap(DIRECTION_ZH, row.direction, "");
    const whyRaw = displayText(row.why_it_matters, "");
    const why = hasCjk(whyRaw) ? whyRaw : "";
    const sectors = (row.affected_sectors || []).map((item) => displayText(item, "")).filter(Boolean);
    const tickers = (row.affected_tickers || []).map((item) => String(item || "").toUpperCase()).filter(Boolean);
    const impact = [...sectors, ...tickers].join(" · ");
    const rankClass = index === 0 ? " rank-1" : "";
    return `<article class="axis-rank-card${rankClass}">
      <span class="rank-badge">Top ${index + 1}</span>
      <h3>${esc(name)} <span class="zone-badge fast">快</span></h3>
      <div class="var-meta">
        ${importance ? chip(`主导程度 ${importance}`, importance === "很高" || importance === "高" ? "intensity-strong" : importance === "中" ? "intensity-mid" : "intensity-weak") : ""}
        ${confidence ? chip(`可信度 ${confidence}`, confidence === "低" ? "cred-low" : "cred-mid") : ""}
        ${trend ? chip(`趋势 ${trend}`, trend === "正在增强" ? "status-watch" : trend === "高位持续" ? "status-ok" : "status-weak") : ""}
        ${status ? chip(status, status === "持续中" ? "status-ok" : status === "观察中" ? "status-watch" : "status-weak") : ""}
      </div>
      ${direction ? `<p class="var-dir">方向：${esc(direction)}</p>` : ""}
      ${listBlock("支持信号", "support", row.supporting_signals)}
      ${listBlock("反向信号", "oppose", row.counter_signals)}
      ${
        why
          ? `<div class="axis-why"><strong>为什么它比其他变量更重要</strong>${esc(why)}</div>`
          : `<p class="muted-empty">重要性质暂未写入</p>`
      }
      <div class="var-impact"><strong>主要影响</strong> ${impact ? esc(impact) : "暂无已关联行业或标的"}</div>
    </article>`;
  }

  function triggerCard(item) {
    const title = displayText(item.title, "");
    if (!title) return "";
    const land = displayText(item.lands_on, "");
    return `<article class="trigger-card">
      <h3>${esc(title)}</h3>
      <span class="muted-empty">影响链暂未展开</span>
      <div class="trigger-meta">
        ${chip("触发事件", "status-watch")}
        ${land ? chip(`落点 → ${land}`, "intensity-mid") : ""}
      </div>
      <p class="trigger-note">作用：改写或强化「${esc(land || "当前主轴")}」。本身不是独立定价主轴。</p>
    </article>`;
  }

  function changeRow(item) {
    const kind = displayText(item.kind_label, "主轴");
    const summary = displayText(item.summary, "近窗记录到实质变化");
    const stamp = formatAsOf(item.created_at).replace("数据截至 ", "").replace("数据时间暂缺", "");
    return `<li><span class="date">${esc(stamp || "—")}</span><span class="body"><strong>${esc(kind)}</strong> · ${esc(
      summary
    )}</span></li>`;
  }

  function renderEmpty() {
    return `
      <section class="status-bar empty-axis">
        <p class="status-line">${EMPTY_DOMINANT}</p>
        <p class="status-hint">定价主轴只来自已落盘、且已跨标的成立的变量。现有数据尚未形成可展示的主轴。</p>
      </section>
      <section class="layer-zone axis-zone">
        <div class="layer-label">
          <h2>当前定价主轴</h2>
          <span class="zone-badge fast">主导变量 · 定价轴</span>
        </div>
        <div class="driver-empty">
          <strong>${EMPTY_DOMINANT}</strong>
          不会为填满三条而补判断。
        </div>
      </section>`;
  }

  function renderReady(data) {
    const drivers = data.dominant_drivers || [];
    const axis = data.pricing_axis || [];
    const triggers = data.trigger_events || [];
    const changes = data.recent_driver_changes || [];
    const tickers = relatedTickers(data);
    const hint = triggers.length
      ? "近窗触发事件另层阅读，不与定价主轴并列。"
      : "近窗暂无改写主轴的触发事件。";
    return `
      <section class="status-bar">
        ${axisRows(axis)}
        ${statusChips(data, drivers)}
        <p class="status-hint">※ ${esc(hint)}</p>
      </section>
      <section class="layer-zone axis-zone">
        <div class="layer-label">
          <h2>当前定价主轴</h2>
          <span class="zone-badge fast">主导变量 · 定价轴</span>
        </div>
        <p class="layer-hint">定价轴 = 市场用什么在给资产定价。主导程度 / 方向 / 可信度 / 趋势 · 支持与反向对称</p>
        <div class="axis-rank">${drivers.map(driverCard).join("")}</div>
      </section>
      <section class="layer-zone trigger-zone">
        <div class="layer-label">
          <h2>触发事件</h2>
          <span class="chip tag-multi">非定价主轴</span>
        </div>
        <p class="layer-hint">触发事件 = 改写或强化某条定价主轴的近窗证据。不与主导变量并列同卡。</p>
        ${
          triggers.length
            ? `<div class="trigger-grid">${triggers.map(triggerCard).join("")}</div>`
            : `<p class="muted-empty">近窗暂无改写主轴的触发事件</p>`
        }
      </section>
      <section class="section">
        <div class="section-head">
          <h2>最近主轴 / 触发变化</h2>
          <span class="section-note">只列近窗真正变化</span>
        </div>
        ${
          changes.length
            ? `<ul class="change-list">${changes.map(changeRow).join("")}</ul>`
            : `<p class="muted-empty">近窗暂无主轴或触发的实质变化</p>`
        }
      </section>
      <section class="section">
        <div class="section-head"><h2>相关标的</h2></div>
        ${
          tickers.length
            ? `<div class="pills">${tickers
                .map((symbol) => `<a class="pill" href="/brain/${esc(symbol)}">${esc(symbol)}</a>`)
                .join("")}</div>`
            : `<p class="muted-empty">暂无已关联标的</p>`
        }
      </section>
      ${
        drivers.length >= 2
          ? `<details class="collapse-panel"><summary>▸ 多解释 / 证据说明</summary><p class="sketch">当前可并列为不同读法，不宜强行单一归因。触发事件与主轴分层阅读，避免把公司级新闻抬成全局定价轴。</p></details>`
          : ""
      }`;
  }

  function showError() {
    document.getElementById("market-root").innerHTML = `
      <section class="status-bar empty-axis">
        <p class="status-line">当前页无法按已落盘数据展示</p>
        <p class="status-hint">请稍后重试。本页不会临时生成分析。</p>
      </section>`;
  }

  async function boot() {
    const root = document.getElementById("market-root");
    const asOf = document.getElementById("as-of");
    try {
      const response = await fetch(OVERVIEW_PATH, { headers: { Accept: "application/json" } });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.llm_invoked) {
        showError();
        return;
      }
      asOf.textContent = formatAsOf(data.as_of);
      const drivers = Array.isArray(data.dominant_drivers) ? data.dominant_drivers : [];
      root.innerHTML = !drivers.length || data.empty_state === EMPTY_DOMINANT ? renderEmpty() : renderReady(data);
    } catch (err) {
      showError();
    }
  }

  boot();
})();
