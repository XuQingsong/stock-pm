(() => {
  "use strict";

  const ctx = window.StockPmStock;
  if (!ctx) return;
  const { $, esc, finite, num, pct, dateText, SYMBOL, MISSING, empty, endpoint, api } = ctx;

  function signed(value, digits = 2) {
    if (!finite(value)) return MISSING;
    const number = Number(value);
    const prefix = number > 0 ? "+" : "";
    return `${prefix}${number.toLocaleString("zh-CN", { maximumFractionDigits: digits })}`;
  }

  function statusPill(status) {
    const text = status || "insufficient";
    return `<span class="status-pill ${esc(text)}">${esc(text)}</span>`;
  }

  function sourceLink(url, label) {
    if (!url) return "—";
    try {
      const parsed = new URL(String(url), location.origin);
      if (!["http:", "https:"].includes(parsed.protocol)) return esc(url);
      return `<a class="source-link" href="${esc(parsed.href)}" target="_blank" rel="noopener noreferrer">${esc(label || parsed.host + parsed.pathname)}</a>`;
    } catch (_) {
      return esc(url);
    }
  }

  function originLabel(origin) {
    if (origin === "primary") return "原始";
    if (origin === "secondary") return "二手";
    return origin || "原始";
  }

  function factId(item) {
    const aliases = { price: "close", price_pressure: "close", close: "close" };
    const raw = String(item.metric || item.id || (item.ref && item.ref.ref_id) || item.ref_id || "").toLowerCase();
    return aliases[raw] || raw;
  }

  function refLine(item) {
    const ref = item.ref || {};
    const source = item.source || ref.source;
    const table = ref.ref_table;
    const id = ref.ref_id || item.ref_id || item.id;
    const asOf = item.as_of || ref.as_of;
    const http = item.http_source || ref.http_source;
    const unit = item.unit || ref.unit;
    const status = item.status || ref.status;
    const origin = item.origin || ref.origin;
    if (!source && !table && !id && !asOf && !http) return "";
    return `<div class="chain-metrics">
      <div><span>source</span><b>${esc(source || "—")}</b></div>
      <div><span>ref</span><b>${esc(table || "evidence")} / ${esc(id || "—")}</b></div>
      <div><span>as_of</span><b>${asOf ? dateText(asOf, true) : "—"}</b></div>
      <div><span>unit</span><b>${esc(unit || "—")}</b></div>
      <div><span>status</span><b>${esc(status || "—")}</b></div>
      <div><span>来源性质</span><b>${esc(originLabel(origin))}</b></div>
      <div><span>http_source</span><b>${sourceLink(http)}</b></div>
    </div>
    <button type="button" class="fact-link" data-fact-id="${esc(factId(item))}" data-metric="${esc(factId(item))}">打开事实详情</button>`;
  }

  function thesisItem(item) {
    return `<article class="chain-item">
      ${statusPill(item.thesis_effect || item.status)}
      <div class="why">${esc(item.what || item.summary || "")}</div>
      <div class="why">为什么重要：${esc(item.why_it_matters || item.why || "—")} · 影响对象：${esc(item.affects || "—")}</div>
      ${item.derived_reason || item.why_thesis_effect ? `<div class="why">${esc(item.derived_reason || item.why_thesis_effect)}</div>` : ""}
      ${refLine(item)}
    </article>`;
  }

  function chainItem(item) {
    const current = finite(item.current) ? num(item.current) : (item.what || "—");
    const previous = finite(item.previous) ? num(item.previous) : "—";
    const delta = finite(item.delta) ? signed(item.delta) : (finite(item.delta_pct) ? pct(item.delta_pct) : "—");
    const window = item.window || "—";
    const why = item.why || item.why_it_matters || item.summary || item.derived_reason || "";
    const affects = item.affects || "";
    const direction = item.direction || item.thesis_effect || "";
    const counter = Array.isArray(item.counter) ? item.counter.join("；") : (item.counter || "");
    return `<article class="chain-item">
      ${statusPill(item.status || item.materiality || item.thesis_effect)}
      <div class="chain-metrics">
        <div><span>当前 vs 前值</span><b>${esc(current)} / ${esc(previous)}</b></div>
        <div><span>delta</span><b>${esc(delta)}</b></div>
        <div><span>窗口</span><b>${esc(window)}</b></div>
        <div><span>方向 / 对象</span><b>${esc(direction || "—")} · ${esc(affects || "—")}</b></div>
      </div>
      ${refLine(item)}
      ${item.mechanism ? `<div class="why">传导机制：${esc(item.mechanism)}${item.chain && item.chain.length ? " · " + esc(item.chain.join(" → ")) : ""}</div>` : ""}
      ${item.exposure ? `<div class="why">暴露：${esc(item.exposure.target || "")} · ${esc(item.exposure.channel || "")} · ${esc(item.exposure.theme || "")}</div>` : ""}
      ${why ? `<div class="why">为什么重要：${esc(why)}</div>` : ""}
      ${counter ? `<div class="counter">反证 / 冲突：${esc(counter)}</div>` : ""}
    </article>`;
  }

  function renderChain(payload) {
    const steps = payload.chain || [];
    return steps.map((step, index) => {
      const items = (step.items || []).map(step.id === "thesis_impact" ? thesisItem : chainItem).join("");
      const empty = !items && step.empty_reason ? `<div class="empty-note">${esc(step.empty_reason)}</div>` : "";
      let body = "";
      if (step.id === "tension") {
        const t = step.tension || (step.items || [])[0] || {};
        if (t.tension && t.tension !== "insufficient") {
          body = `<article class="chain-item">
            ${statusPill(t.tension || t.status)}
            <div class="chain-metrics">
              <div><span>价格变动 %</span><b>${esc(finite(t.price_change) ? signed(t.price_change) : "—")}</b></div>
              <div><span>预期变动 %</span><b>${esc(finite(t.fundamentals_change) ? signed(t.fundamentals_change) : "—")}</b></div>
              <div><span>张力</span><b>${esc(t.tension || t.status || "—")}</b></div>
              <div><span>code</span><b>${esc(t.code || "—")}</b></div>
            </div>
            <div class="why">${esc(t.reason || t.why || "")}</div>
          </article>`;
        } else {
          body = empty || `<div class="empty-note">${esc(t.reason || step.empty_reason || "缺少价格或预期变动，不能描述张力")}</div>`;
        }
      } else if (step.id === "causal_impact") {
        const conf = step.confirmation || {};
        const confItems = (conf.used || conf.series || []).map(chainItem).join("");
        const clues = (step.clues || []).map((clue) => `<article class="chain-item">${statusPill(clue.status)}<div class="why">${esc(clue.headline || "")} · ${esc(clue.why || "")}</div>${refLine(clue)}</article>`).join("");
        body = `<div class="causal-block">
            <h4>Market Confirmation ${statusPill(conf.status)}</h4>
            <p class="why">${esc(conf.reason || "")}</p>
            ${confItems || `<div class="empty-note">${esc(conf.reason || "未评估市场确认")}</div>`}
            ${clues}
          </div>
          <div class="causal-block">
            <h4>Transmission ${statusPill(step.transmission_status || step.status)}</h4>
            ${items || (step.transmission_empty ? `<div class="empty-note">${esc(step.transmission_empty)}</div>` : empty)}
          </div>`;
      } else if (step.id === "thesis_impact") {
        const fields = (step.changed_fields || []).join("、") || "无";
        body = `${items || empty}
          <article class="chain-item"><div class="why">Thesis ${step.thesis_changed ? "已变化" : "未变化"}。changed_fields：${esc(fields)}。张力 ${esc(step.tension_status || "—")}。${esc(step.derived_reason || step.summary || "")}</div></article>`;
      } else {
        body = items || empty;
      }
      return `<div class="chain-step">
        <div class="chain-rail" aria-hidden="true"><span class="chain-dot"></span>${index < steps.length - 1 ? '<span class="chain-line"></span>' : ""}</div>
        <div class="chain-body">
          <div class="chain-kicker">${esc(step.title)}</div>
          <h3>${esc(step.title_zh)}${statusPill(step.status)}</h3>
          ${body}
        </div>
      </div>`;
    }).join("");
  }

  function chainCounts(overall) {
    const counts = overall.available_counts || {};
    const parts = ["L3", "L2", "L1"].filter((key) => Number(counts[key] || 0) > 0)
      .map((key) => `${counts[key]} 条 ${key}`);
    return parts.join("、") || "无可用链";
  }

  function renderChainGroups(payload) {
    const groups = payload.chains || [];
    return `<div class="chain-groups">${groups.map((group) => {
      const gaps = (group.blocking_gaps || []).map((row) => `${row.code} → ${row.affects_chain}/${row.affects_stage}`).join("；") || "无";
      const stages = (group.affected_stages || []).join("、") || "—";
      const upgrade = group.level === "L3" ? "本链已完整，不伪装其他链的缺口" : (group.next_required_evidence || "补该链下一层证据");
      const body = `<div class="chain-metrics">
          <div><span>level</span><b>${esc(group.level)}</b></div>
          <div><span>scope</span><b>${esc(group.scope || "—")}</b></div>
          <div><span>affected stages</span><b>${esc(stages)}</b></div>
        </div>
        <div class="why">可确定：${esc(group.validated_conclusion || "—")}</div>
        <div class="why">缺口影响：${esc(gaps)}</div>
        <div class="why">升级到下一等级：${esc(upgrade)}</div>
        ${refLine(group)}`;
      return `<article class="chain-group${group.level === "L0" ? " is-empty" : ""}">
        <h3>${esc(group.title_zh)} <span class="chain-kicker">${esc(group.title)}</span>${statusPill(group.level)}</h3>
        ${body}
      </article>`;
    }).join("")}</div>`;
  }

  function overallDirectionLabel(payload) {
    const overall = payload.overall || {};
    const level = overall.level || "L0";
    if (overall.conflict || overall.status === "conflict") return "conflict（无统一个股方向）";
    if (payload.can_form_direction === true) return overall.direction || "—";
    if (level === "L0") return "unavailable";
    return "无（未达 L3，不输出方向）";
  }

  function renderGradeBoard(payload) {
    const overall = payload.overall || {};
    const level = overall.level || "L0";
    const status = overall.status || level;
    const blocked = payload.cannot_form_judgment && level === "L0";
    const banner = payload.synthetic
      ? `<div class="decision-banner" role="status">合成演示数据 · ${esc(payload.preview_label || "preview")}。生产环境不会用 fixture 顶替真实数据。</div>`
      : "";
    const l0 = blocked
      ? `<div class="decision-banner decision-blocked" role="status">${esc(payload.cannot_form_judgment_reason || "目前不能形成判断")}</div>`
      : "";
    return `${banner}${l0}
      <header class="decision-head">
        <h2 id="decision-heading">动态判断</h2>
        <div class="grade-board" role="status">
          <div class="grade-level">当前可用等级 <b>${esc(level)}</b>${statusPill(status)} · 方向 <b>${esc(overallDirectionLabel(payload))}</b></div>
          <p>目前可以确定什么：${esc(overall.can_determine || "尚无可用结论")}</p>
          <p>目前不能确定什么：${esc(overall.cannot_determine || "尚不能输出方向性 Thesis")}</p>
          <p>可用链数量：${esc(chainCounts(overall))}</p>
        </div>
      </header>`;
  }

  function comparisonBlock(item) {
    const current = finite(item.current) || finite(item.value) ? num(item.current ?? item.value) : "—";
    const previous = finite(item.previous) ? num(item.previous) : "—";
    const delta = finite(item.delta) ? signed(item.delta) : (finite(item.delta_pct) ? pct(item.delta_pct) : "—");
    return `<div class="chain-metrics">
      <div><span>series</span><b>${esc(item.series || item.metric || "—")}</b></div>
      <div><span>单位</span><b>${esc(item.unit || "—")}</b></div>
      <div><span>期间</span><b>${esc(item.period || item.as_of || "—")} vs ${esc(item.previous_period || item.previous_as_of || "—")}</b></div>
      <div><span>current / prior / delta</span><b>${esc(current)} / ${esc(previous)} / ${esc(delta)}</b></div>
      <div><span>公式</span><b>${esc(item.formula || item.comparison || "同序列同单位比较")}</b></div>
      <div><span>方向</span><b>${esc(item.direction || "—")}</b></div>
    </div>`;
  }

  function renderRatesPath(path) {
    if (!path) return `<div class="empty-note">利率贴现链未形成</div>`;
    if (path.status === "not_applicable") {
      return `<div class="empty-note">${esc(path.reason || "该标的没有高估值久期暴露，利率贴现链不进入个股主结论")}</div>`;
    }
    const nodes = (path.nodes || []).map((node) => `<article class="path-node" data-layer="${esc(node.layer || "")}">
      <div class="chain-kicker">${esc(node.layer || "node")}</div>
      <h4>${esc(node.title || node.id)}</h4>
      ${statusPill(node.status || node.direction || path.status)}
      <div class="why">方向 ${esc(node.direction || "—")} · 机制 ${esc(node.mechanism || node.channel || "—")}</div>
      ${node.value != null ? `<div class="why">current ${esc(String(node.value))} ${esc(node.unit || "")} · as_of ${esc(node.as_of || "—")}</div>` : ""}
      <div class="why">source ${esc(node.source || "—")} · 置信度 ${esc(node.confidence || path.confidence || "—")}</div>
      ${node.does_not_imply ? `<div class="counter">不推出：${esc(node.does_not_imply)}</div>` : ""}
      <button type="button" class="fact-link" data-fact-id="${esc(node.metric || node.id)}">引用事实</button>
    </article>`).join("");
    const edges = (path.edges || []).map((edge) => `<article class="path-edge">
      <div class="chain-kicker">${esc(edge.from)} → ${esc(edge.to)}</div>
      <div class="why">方向 ${esc(edge.direction || "—")} · 机制 ${esc(edge.mechanism || "—")}</div>
      <div class="why">as_of ${esc(edge.as_of || "—")} · 置信度 ${esc(edge.confidence || "—")}</div>
      <div class="counter">失效条件：${esc(edge.invalidation || path.invalidation || "—")}</div>
      <button type="button" class="fact-link" data-fact-id="${esc((edge.evidence || [])[0] || edge.from)}">引用事实</button>
    </article>`).join("");
    return `<div class="rates-path" data-status="${esc(path.status || "")}" data-direction="${esc(path.direction || "")}" data-horizon="${esc(path.horizon || "")}">
      <p class="why">Fact → Change → Expectation → Impact → What changes。置信度 ${esc(path.confidence || "—")}。失效：${esc(path.invalidation || "—")}</p>
      <p class="why">影响方向 ${esc(path.direction || "—")} · 期限 ${esc(path.horizon || "—")}。未形成个股交易方向时仍回答传导方向/期限，不输出买卖指令。</p>
      <div class="path-nodes">${nodes}</div>
      <div class="path-edges">${edges}</div>
    </div>`;
  }

  function renderRiskState(risk) {
    if (!risk) return `<div class="empty-note">没有可追溯 VIX，风险状态不编造</div>`;
    return `<article class="risk-state">
      <h4>VIX 只改变风险状态</h4>
      ${statusPill(risk.status)}
      <div class="why">VIX ${esc(String(risk.current ?? "—"))} vs ${esc(String(risk.previous ?? "—"))} ${esc(risk.unit || "")} · as_of ${esc(risk.as_of || "—")}</div>
      <div class="why">传导：${esc(risk.affects || "risk_state")}。禁止直接推出 ${esc(risk.does_not_imply || "个股涨跌方向")}</div>
      <div class="counter">反证 / 失效：${esc(risk.invalidation || "—")}</div>
      <button type="button" class="fact-link" data-fact-id="vix">打开 VIX 事实</button>
    </article>`;
  }

  function renderLayers(payload) {
    const layers = payload.layers || [];
    return `<ol class="causal-layers">${layers.map((layer) => {
      let body = "";
      if (layer.id === "impact") {
        body = `${renderRatesPath(layer.path || payload.rates_path)}${renderRiskState(layer.risk_state || payload.risk_state)}`;
        if ((layer.items || []).length) {
          body += (layer.items || []).map(chainItem).join("");
        }
      } else if (layer.id === "what_changes") {
        body = (layer.items || []).map(thesisItem).join("") || `<div class="empty-note">主结论尚未改写方向</div>`;
      } else if (layer.id === "fact" || layer.id === "change") {
        body = (layer.items || []).map((item) => `<article class="chain-item" data-metric="${esc(factId(item))}">
          ${statusPill(item.status || item.materiality)}
          <h4>${esc(item.name || item.metric || item.kind || "fact")}</h4>
          ${comparisonBlock(item)}
          ${refLine(item)}
        </article>`).join("") || `<div class="empty-note">本层暂无进入个股主结论的项目</div>`;
      } else {
        body = (layer.items || []).map(chainItem).join("") || `<div class="empty-note">本层数据不足</div>`;
      }
      return `<li class="causal-layer" data-layer="${esc(layer.id)}">
        <div class="chain-kicker">${esc(layer.title)}</div>
        <h3>${esc(layer.title_zh)}</h3>
        ${body}
      </li>`;
    }).join("")}</ol>`;
  }

  function renderBackground(rows) {
    const items = (rows || []).map((row) => `<article class="chain-item">
      <h4>${esc(row.name || row.metric)}</h4>
      ${comparisonBlock(row)}
      ${refLine(row)}
      <div class="why">市场背景，不写入该股主结论</div>
    </article>`).join("") || `<div class="empty-note">没有折叠的市场背景宏观</div>`;
    return `<details class="market-background fold"><summary>市场背景宏观（不进入个股主结论）</summary>${items}</details>`;
  }

  function openFactDrawer(payload, factIdWanted) {
    const drawer = $("fact-drawer");
    const body = $("fact-drawer-body");
    if (!drawer || !body) return;
    const catalog = []
      .concat(payload.facts || [])
      .concat(payload.market_background || [])
      .concat(((payload.layers || []).find((row) => row.id === "change") || {}).items || [])
      .concat(((payload.rates_path || {}).nodes || []))
      .concat(payload.risk_state ? [payload.risk_state] : []);
    const aliases = { price: "close", price_pressure: "close", close: "close" };
    const wanted = aliases[String(factIdWanted || "").toLowerCase()] || String(factIdWanted || "").toLowerCase();
    const item = catalog.find((row) => {
      const id = String(factId(row) || "").toLowerCase();
      const metric = String(row.metric || "").toLowerCase();
      const rowId = String(row.id || "").toLowerCase();
      return id === wanted || metric === wanted || rowId === wanted;
    });
    if (!item) {
      body.innerHTML = `<p>未找到内部事实 ${esc(factIdWanted)}</p>`;
    } else {
      const ref = item.ref || {};
      const metric = factId(item) || wanted;
      const source = item.source || ref.source || "";
      const asOf = item.as_of || ref.as_of || "";
      const unit = item.unit || ref.unit || "";
      const status = item.status || ref.status || "";
      const http = item.http_source || ref.http_source || "";
      body.innerHTML = `<h3 data-drawer-metric="${esc(metric)}">事实详情 · ${esc(item.name || item.metric || factIdWanted)}</h3>
        <p>内部 id：${esc(metric)}</p>
        ${comparisonBlock({ ...item, current: item.current ?? item.value })}
        <p data-drawer-source="${esc(source)}" data-drawer-as-of="${esc(asOf)}" data-drawer-unit="${esc(unit)}" data-drawer-status="${esc(status)}">source ${esc(source || "—")} · as_of ${esc(asOf || "—")} · unit ${esc(unit || "—")}</p>
        <p>status ${esc(status || "—")} · 原始/二手：${esc(originLabel(item.origin || ref.origin))}</p>
        <p>http_source：${sourceLink(http)}</p>`;
    }
    if (typeof drawer.showModal === "function") drawer.showModal();
  }

  function bindFactLinks(root, payload) {
    root.querySelectorAll(".fact-link").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.preventDefault();
        openFactDrawer(payload, btn.getAttribute("data-fact-id"));
      });
    });
  }

  function renderDecision(payload) {
    const thesis = payload.thesis || {};
    const compared = payload.compared_to || {};
    const overall = payload.overall || {};
    const canDirect = payload.can_form_direction === true;
    const conflict = overall.conflict === true || overall.status === "conflict";
    const quality = payload.evidence_quality || thesis.evidence_quality || "insufficient";
    const directionLabel = overallDirectionLabel(payload);
    const thesisStatus = canDirect ? (thesis.status || "ok") : (conflict ? "conflict" : "incomplete");
    const gaps = (payload.gaps || []).map((row) => `<li>${esc(row.text || row.code)} <small>${esc(row.affects_chain || "")}/${esc(row.affects_stage || "")}</small></li>`).join("");
    const blockedThesis = conflict
      ? "<li>同等强度 L3 方向冲突，不输出统一个股方向</li>"
      : "<li>未达 L3，不把局部事实写成方向性 Thesis</li>";
    const bulls = canDirect
      ? ((thesis.bull_drivers || []).map((row) => `<li>${esc(row.text)} <small>${esc((row.based_on || []).join(", "))}</small></li>`).join("") || "<li>暂无合格多头证据</li>")
      : blockedThesis;
    const bears = canDirect
      ? ((thesis.bear_drivers || []).map((row) => `<li>${esc(row.text)} <small>${esc((row.based_on || []).join(", "))}</small></li>`).join("") || "<li>暂无合格空头证据</li>")
      : blockedThesis;
    const facts = (payload.facts || []).map((row) => {
      const ref = row.ref || {};
      return `<li>${esc(row.kind || "fact")} · ${esc(row.metric || "")} · ${esc(ref.source || row.source || "")} · ${esc(ref.as_of || row.as_of || "")} · ${esc(ref.ref_table || "")}/${esc(ref.ref_id || "")}</li>`;
    }).join("") || "<li>没有可折叠的原始事实</li>";
    const noMove = payload.no_material_change ? `<p class="subline">无重大变化：${esc((payload.what_changed || {}).summary || "原判断不变")}</p>` : "";
    const body = $("decision-body") || $("decision-module");
    body.className = "";
    const injectNote = (payload.inject || []).length
      ? `<div class="decision-banner" role="status">测试注入 ${esc((payload.inject || []).join(", "))}（仅测试/预览环境）</div>`
      : "";
    const withheld = !canDirect
      ? `<div class="decision-banner" role="status">历史事实与预测已区分：can_form_direction=false，页面不展示无来源方向或百分比预测。</div>`
      : "";
    body.innerHTML = `      ${renderGradeBoard(payload)}
      ${injectNote}${withheld}
      ${noMove}
      ${gaps ? `<ul class="decision-gaps">${gaps}</ul>` : ""}
      <section class="causal-flow" aria-label="Fact Change Expectation Impact What changes">
        <h3>Fact → Change → Expectation → Impact → What changes</h3>
        ${renderLayers(payload)}
        ${renderRiskState(payload.risk_state)}
        ${renderBackground(payload.market_background)}
      </section>
      <details class="decision-chain-fold fold"><summary>兼容技术链（默认折叠）</summary>
        ${renderChainGroups(payload)}
        <div class="decision-chain">${renderChain(payload)}</div>
      </details>
      <div class="decision-sides">
        <section class="decision-side"><h3>Bull</h3><ul>${bulls}</ul></section>
        <section class="decision-side"><h3>Bear</h3><ul>${bears}</ul></section>
      </div>
      <p class="subline">关键分歧：${esc(canDirect ? (thesis.key_disagreement || "尚未形成") : "局部判断不成方向")} · 失效条件：${esc(canDirect ? (thesis.invalidation || "尚未形成") : "需先补齐 L3 所需环节")}</p>
      <p class="subline">标的 ${esc(payload.symbol || SYMBOL)} · 数据截止 ${dateText(payload.as_of, true)} · 证据质量 ${esc(quality)} · Thesis ${statusPill(thesisStatus)} <b>${esc(directionLabel)}</b> · 相对上次 ${dateText(compared.as_of, true)}</p>
      <details class="decision-facts fold"><summary>原始 Facts（默认折叠）</summary><ul>${facts}</ul></details>`;
    bindFactLinks(body, payload);
    body.dataset.decisionReady = "1";
    body.setAttribute("data-decision-ready", "1");
  }

  function extraQuery() {
    const params = new URLSearchParams(location.search);
    const next = new URLSearchParams();
    const preview = params.get("preview");
    const inject = params.get("inject");
    if (preview) next.set("preview", preview);
    if (inject) next.set("inject", inject);
    const macroInject = params.get("macro_inject");
    if (macroInject) next.set("macro_inject", macroInject);
    const qs = next.toString();
    return qs ? `?${qs}` : "";
  }

  function healthReasonCopy(row) {
    const code = row.reason_code || "";
    if (code === "source_not_configured") return "源未配置";
    if (code === "upstream_empty") return "上游无记录";
    if (code === "record_stale") return "记录过旧";
    if (code === "record_invalid") return "记录格式非法";
    if (code === "query_error") return "查询异常";
    if (code === "missing_observation") return "缺少观察时间";
    if (code === "upstream_unavailable") return "上游已不可用";
    if (code === "deprecated") return "序列已停更";
    return row.reason_label || code || "状态未知";
  }

  function renderDataHealth(health) {
    if (!health) return "";
    const overall = health.overall || {};
    const names = { price: "价格", earnings: "盈利", macro_rates: "宏观", risk_sentiment: "风险" };
    const list = (ids) => (ids || []).map((id) => names[id] || id).join("、") || "无";
    const banner = health.synthetic
      ? `<div class="decision-banner health-synthetic" role="status" data-runtime="synthetic">SYNTHETIC SCENARIO · 合成演示数据 · 非实时 · ${esc(health.preview_label || "preview")}。fixture 不得冒充实时。</div>`
      : `<div class="health-mode" role="status" data-runtime="real">REAL RUNTIME · 实盘观察 · 非合成 fixture${health.runtime_fetched_at ? ` · ${esc(health.runtime_fetched_at)}` : ""}</div>`;
    const inputRows = (health.datasets || []).map((row) => {
      const title = row.title_zh || row.dataset;
      const age = row.freshness_age == null ? "—" : `${row.freshness_age}天`;
      const series = row.series_or_symbol || row.series || "—";
      const value = row.value == null || row.value === "" ? "—" : String(row.value);
      const unit = row.unit || "—";
      return `<tr class="status-${esc(row.status)}">
        <td>${esc(title)}</td>
        <td>${esc(row.source || "—")}<div class="why">${sourceLink(row.http_source)}</div></td>
        <td>${esc(series)}</td>
        <td>${esc(row.as_of || "—")}</td>
        <td>${esc(value)}</td>
        <td>${esc(unit)}</td>
        <td>${esc(age)}</td>
        <td>${statusPill(row.status)}</td>
      </tr>`;
    }).join("");
    const rows = (health.datasets || []).map((row) => {
      const age = row.freshness_age == null ? "—" : `${row.freshness_age} 天 / 阈值 ${row.freshness_threshold ?? "—"} 天`;
      const title = row.title_zh || row.dataset;
      return `<article class="health-row status-${esc(row.status)}">
        <h4>${esc(title)} · ${esc(row.dataset)} ${statusPill(row.status)}</h4>
        <div class="why">原因：${esc(healthReasonCopy(row))} <small>${esc(row.reason_code || "")}</small></div>
        <div class="why">作用：${esc(row.affects_chain || "—")} / ${esc(row.affects_stage || "—")} · source ${esc(row.source || "—")} · series_or_symbol ${esc(row.series_or_symbol || row.series || "—")}</div>
        <div class="why">as_of ${esc(row.as_of || "—")} · value ${esc(row.value == null ? "—" : String(row.value))} ${esc(row.unit || "")} · 观察 ${esc(row.latest_observed_at || "—")} · 入库 ${esc(row.latest_ingested_at || "—")} · 陈旧程度 ${esc(age)}</div>
        <div class="why">http_source ${sourceLink(row.http_source)} · transport ${esc(row.transport || "—")}</div>
        <div class="why">恢复：${esc(row.next_action || "—")}${row.required_env ? ` · 所需环境变量 ${esc(row.required_env)}` : ""}</div>
        ${row.historical_series_or_symbol ? `<div class="why">历史 FRED ${esc(row.historical_series_or_symbol)} · ${esc(row.historical_status || "")} / ${esc(row.historical_reason_code || "")} · 不得当作当前金价</div>` : ""}
      </article>`;
    }).join("");
    return `<section class="data-health" aria-label="数据健康" data-mode="${health.synthetic ? "synthetic" : "live"}" data-runtime="${health.synthetic ? "synthetic" : "real"}">
      ${banner}
      <div class="health-compact">
        <strong>数据健康</strong>
        <span class="status-pill ${esc(overall.status || "degraded")}">${esc(overall.status || "degraded")}</span>
        <span>可用链：${esc(list(overall.available_chains))}</span>
        <span>受限链：${esc(list(overall.limited_chains))}</span>
        <span>不可用链：${esc(list(overall.unavailable_chains))}</span>
        <span class="status-pill ${esc((health.database && health.database.status) || "ok")}">数据库 ${esc((health.database && (health.database.database || health.database.status)) || "unknown")}</span>
        ${eventsCoverageChip(health.events_coverage)}
      </div>
      ${health.database && health.database.status === "error" ? `<p class="subline">数据库不可达或写入失败：${esc(health.database.note || "PostgreSQL unreachable; live overlay does not hide this")}</p>` : ""}
      <p class="subline">${esc((overall.note) || "数据健康只描述证据可用性，不是投资结论")}</p>
      <table class="health-inputs">
        <caption>各输入的 source / series_or_symbol / as_of / value / unit / 新鲜度 / 状态。ICE DXY 保持 not_configured/unavailable；DTWEXBGS 只显示为 broad_usd_proxy 广义美元代理，不得称为 DXY。FRED GOLDPMGBD228NLBM 已停更，不得当作当前金价；实时黄金需 ALPHA_VANTAGE_API_KEY。NVDA 日线需 ALPACA_API_KEY_ID 与 ALPACA_API_SECRET_KEY；盈利需 FMP_API_KEY。不在页面展示密钥。</caption>
        <thead><tr><th>输入</th><th>source</th><th>series_or_symbol</th><th>as_of</th><th>value</th><th>unit</th><th>新鲜度</th><th>状态</th></tr></thead>
        <tbody>${inputRows}</tbody>
      </table>
      <details class="health-details">
        <summary>展开缺口、陈旧程度、作用范围和恢复条件</summary>
        <div class="health-rows">${rows}</div>
      </details>
    </section>`;
  }

  async function loadDataHealth() {
    const slot = $("data-health-slot");
    if (!slot) return;
    const path = endpoint("data-health") + extraQuery();
    try {
      const health = await api(path);
      slot.innerHTML = renderDataHealth(health);
    } catch (error) {
      slot.innerHTML = `<section class="data-health"><p class="subline">数据健康加载失败：${esc(error.message || "未知错误")}</p></section>`;
    }
  }

  function eventsCoverageChip(cover) {
    if (!cover) return "";
    const product = cover.product_status || {};
    const health = product.source_health || {};
    const evidence = product.evidence_sufficiency || {};
    const conclude = product.can_conclude || {};
    const google = ((cover.providers || {}).google_cse || {}).status || "not_configured";
    const mode = cover.data_mode || "empty";
    return `<span class="status-pill ${(health.ok ? "ok" : "not_configured")}" data-events-coverage="1" data-data-mode="${esc(mode)}" data-live="${cover.live ? "1" : "0"}" data-source-health="${health.ok ? "1" : "0"}" data-google-status="${esc(google)}">${esc(health.label || "数据源不完整")} · ${esc(evidence.label || "证据不足")} · ${esc(conclude.label || "尚不能形成结论")} · ${esc(conclude.reason || "")}</span>`;
  }

  async function loadEvents() {
    const body = $("event-body");
    if (!body) return;
    try {
      const payload = await api(`/api/stock/${encodeURIComponent(SYMBOL)}/events${extraQuery()}`);
      const ui = window.StockPmEvents;
      if (!ui) throw new Error("事件渲染未加载");
      const coverNode = $("event-coverage");
      if (coverNode) {
        const cover = ui.renderCoverage(payload.coverage || {});
        coverNode.innerHTML = cover.html;
        coverNode.dataset.googleStatus = cover.googleStatus;
        coverNode.dataset.dataMode = cover.dataMode || payload.data_mode || "empty";
        coverNode.dataset.live = payload.live ? "1" : "0";
        coverNode.dataset.replay = payload.recorded_replay ? "1" : "0";
      }
      body.className = "";
      body.innerHTML = ui.renderStock(payload);
      body.dataset.eventsReady = "1";
      body.dataset.symbol = SYMBOL;
      body.dataset.eventCount = String((payload.events || []).length);
      body.dataset.dataMode = payload.data_mode || "empty";
      body.dataset.live = payload.live ? "1" : "0";
      body.dataset.replay = payload.recorded_replay ? "1" : "0";
      const module = $("event-module");
      if (module) module.dataset.eventsReady = "1";
    } catch (error) {
      body.className = "";
      body.dataset.eventsReady = "error";
      body.innerHTML = `<div class="empty-note">相关事件暂不可用，只影响事件链：${esc(error.message || "未知错误")}</div>`;
    }
  }

  async function loadDecision() {
    const body = $("decision-body") || $("decision-module");
    if (!body) return;
    // Same gate as GET /api/stock/{symbol}/decision: the API ignores preview
    // and inject unless the matching ENABLE_* flag is on and APP_ENV is
    // development/test/local. Public query params cannot enable them.
    const path = endpoint("decision") + extraQuery();
    try {
      const payload = await api(path);
      renderDecision(payload);
    } catch (error) {
      body.className = "";
      body.dataset.decisionReady = "error";
      body.innerHTML = `<div class="state error"><b>动态判断加载失败</b><span>${esc(error.message || "未知错误")}</span></div>`;
    }
  }

  loadDecision();
  loadDataHealth();
  loadEvents();
})();
