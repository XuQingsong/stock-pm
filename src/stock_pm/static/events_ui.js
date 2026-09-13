(() => {
  "use strict";

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);

  const safeUrl = (value) => {
    try {
      const u = new URL(String(value));
      if (!["http:", "https:"].includes(u.protocol)) return "";
      if (u.username || u.password) return "";
      const host = (u.hostname || "").toLowerCase();
      if (!host || host === "localhost" || host === "127.0.0.1" || host.endsWith(".invalid") || host === "example.com" || host.endsWith(".example.com")) {
        return "";
      }
      return u.href;
    } catch (_) {
      return "";
    }
  };

  const sourceLink = (url, label) => {
    const href = safeUrl(url);
    if (!href) return `<span class="no-url">无原文</span>`;
    return `<a class="source-link" href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(label || href)}</a>`;
  };

  const pill = (text, cls = "") =>
    `<span class="status-pill ${esc(cls)}">${esc(text)}</span>`;

  const tierClass = (source) => {
    if (source.content_type === "official_fact" || source.fact_or_opinion === "fact" && source.source_tier === 1) {
      return "tier-fact";
    }
    if (source.content_type === "research_opinion" || source.fact_or_opinion === "opinion") {
      return "tier-opinion";
    }
    return "tier-media";
  };

  const laneLabel = {
    official_fact: "官方事实 · Tier 1 · 原文优先",
    media_report: "媒体报道 · Tier 2 · 仅用于确认",
    research_opinion: "机构观点 · Tier 3 · 不得升级为事实",
    aggregator: "聚合发现 · 不得作为最终证据"
  };

  const refsHtml = (refs) => {
    const rows = (refs || []).filter((row) => safeUrl(row.source_url || row.canonical_url));
    if (!rows.length) return `<span class="no-url">证据不足，withhold</span>`;
    return rows.map((row) =>
      sourceLink(row.source_url || row.canonical_url, `${row.publisher || "原文"} · T${row.source_tier || ""}`)
    ).join(" · ");
  };

  const boundHtml = (item) => {
    if (!item) return "—";
    if (typeof item === "string") return esc(item);
    const text = item.text == null || item.text === "" ? "—" : esc(item.text);
    return `${text}<div class="evidence-refs">证据：${refsHtml(item.evidence_refs)}</div>`;
  };

  const LAYER_LABELS = {
    fact: "Fact · 已确认事实",
    change: "Change · 相对基线的变化",
    expectation: "Expectation · 方向 / 期限 / 置信度",
    impact: "Impact · 市场与暴露",
    what_changes: "What changes · 什么变了"
  };

  const causalChainHtml = (analysis) => {
    const chain = (analysis && analysis.causal_chain) || {};
    const layers = chain.layers || [];
    if (!layers.length) return "";
    return `<ol class="event-causal-chain" data-causal-chain="1" data-chain-complete="${chain.complete ? "1" : "0"}">
      ${layers.map((layer) => {
        const cites = (layer.cites || []).join(" ");
        const extra = [];
        if (layer.id === "fact" && layer.excerpt) {
          extra.push(`<div class="subline" data-fact-excerpt="1">原文：${esc(layer.excerpt)}</div>`);
        }
        if (layer.id === "expectation") {
          extra.push(`<div class="subline">方向 ${esc(layer.direction || "—")} · 期限 ${esc(layer.horizon || "—")} · 置信度 ${esc(layer.confidence || "—")}</div>`);
        }
        if (layer.id === "impact") {
          extra.push(exposuresHtml(layer.exposures || analysis.exposures || []));
        }
        if (layer.id === "what_changes") {
          if (layer.invalidation) extra.push(`<div class="subline">失效：${esc(layer.invalidation)}</div>`);
          if (layer.follow_up) extra.push(`<div class="subline">后续观察：${esc(layer.follow_up)}</div>`);
        }
        return `<li class="event-causal-layer" data-causal-layer="1" data-layer="${esc(layer.id)}" data-layer-id="${esc(layer.layer_id || "")}" data-cites="${esc(cites)}">
          <div class="chain-kicker">${esc(LAYER_LABELS[layer.id] || layer.id)}</div>
          <div data-layer-text="1">${esc(layer.text || "")}</div>
          ${layer.evidence_refs && layer.evidence_refs.length ? `<div class="evidence-refs">证据：${refsHtml(layer.evidence_refs)}</div>` : ""}
          ${extra.join("")}
        </li>`;
      }).join("")}
    </ol>`;
  };

  const answersHtml = (event, why) => {
    const analysis = event.analysis || {};
    const answers = analysis.answers || {};
    const credibility = answers.credibility || (analysis.confidence && analysis.confidence.text) || "—";
    const what = answers.what_happened || event.canonical_title || "—";
    const relevant = why || answers.why_relevant || "市场事件中心完整展示";
    const duration = answers.how_long || event.duration || "unspecified";
    const invalid = answers.invalidates_when || event.invalidation || "—";
    return `<div class="event-answers" data-answers="1">
      <div data-answer="what"><span>发生了什么</span><b>${esc(what)}</b></div>
      <div data-answer="credibility"><span>可信度</span><b>${esc(credibility)}</b></div>
      <div data-answer="why"><span>为何相关</span><b>${esc(relevant)}</b></div>
      <div data-answer="duration"><span>影响多久</span><b>${esc(duration)}</b></div>
      <div data-answer="invalidation"><span>何时失效</span><b>${esc(invalid)}</b></div>
    </div>`;
  };

  const sourcesByLane = (sources) => {
    const lanes = { official_fact: [], media_report: [], research_opinion: [], aggregator: [] };
    for (const source of sources || []) {
      const key = lanes[source.content_type] ? source.content_type : "aggregator";
      lanes[key].push(source);
    }
    return lanes;
  };

  const sourceRow = (source) => {
    const href = safeUrl(source.source_url || source.canonical_url);
    return `<div class="source-row" data-content-type="${esc(source.content_type)}" data-fact-or-opinion="${esc(source.fact_or_opinion)}" data-source-tier="${esc(source.source_tier)}">
      ${pill(source.content_type, tierClass(source))}
      ${pill(`Tier ${source.source_tier}`)}
      ${pill(source.fact_or_opinion, source.fact_or_opinion === "fact" ? "tier-fact" : "tier-opinion")}
      ${source.document_role ? pill(source.document_role) : ""}
      ${href ? sourceLink(href, source.publisher || source.title) : `<span class="no-url">${esc(source.publisher || "无原文")}</span>`}
      <div class="news-meta">${esc(source.title || "")} · ${esc(source.published_at || "")}</div>
    </div>`;
  };

  const timelineHtml = (timeline) => {
    if (!timeline || !timeline.length) return "";
    return `<div class="event-timeline" data-timeline="1">
      <h4>同一事件时间线</h4>
      ${timeline.map((row) =>
        `<div class="timeline-item" data-timeline-item="1" data-timeline-status="${esc(row.status || "")}" data-polarity="${esc(row.polarity || "")}" data-phase="${esc(row.phase || "")}" data-what-changes="${esc(row.what_changes || "")}">
          <div class="news-meta">${esc(row.observed_at || row.event_time || "时间未标注")} · valid_from ${esc(row.valid_from || "—")} · ${esc(row.publisher || "")} · ${esc(row.status || "")}${row.supersedes ? ` · supersedes ${esc(row.supersedes)}` : ""}</div>
          <div>${esc(row.claim || "")}</div>
          <div class="subline">${esc(row.what_changes || "")}</div>
          <div class="evidence-refs">${row.source_url ? sourceLink(row.source_url, row.publisher || "原文") : "<span class='no-url'>无来源</span>"}</div>
        </div>`
      ).join("")}
    </div>`;
  };

  const claimsHtml = (claims) => {
    if (!claims || !claims.length) return "";
    return `<div class="event-claims">${claims.map((claim) =>
      `<div class="claim-row" data-polarity="${esc(claim.polarity)}" data-claim-status="${esc(claim.status || "")}" data-claim-source="${esc(claim.source_url || "")}">
        ${pill(claim.polarity, claim.polarity === "contradicts" && claim.status !== "superseded" ? "conflict" : "")}
        ${esc(claim.text)}
        ${claim.excerpt ? `<div class="subline" data-claim-excerpt="1">${esc(claim.excerpt)}</div>` : ""}
        <div class="evidence-refs">${claim.source_url ? sourceLink(claim.source_url, claim.publisher || "原文") : "<span class='no-url'>无来源</span>"}</div>
      </div>`
    ).join("")}</div>`;
  };

  const exposuresHtml = (exposures) => {
    if (!exposures || !exposures.length) return "<p class='subline'>无个股暴露映射。战争标题不会机械复制到全部股票。</p>";
    return exposures.map((row) =>
      `<div class="exposure-row" data-exposure-symbol="${esc(row.symbol)}" data-channel="${esc(row.channel)}">
        <b>${esc(row.symbol)}</b> · ${esc(row.channel)} · ${esc(row.mechanism)}
        <div class="why-relevant">${esc(row.why_relevant)}</div>
      </div>`
    ).join("");
  };

  const providerPill = (coverage, name) => {
    const row = ((coverage || {}).providers || {})[name] || {};
    const status = row.status || "idle";
    return `${pill(`${name} ${status}`, status)}<span>${esc(name)} events ${esc(row.event_count ?? 0)} · last_success ${esc(row.last_success_at || "—")} · ${esc(row.reason_code || "ok")}</span>`;
  };

  const productRow = (key, block) => {
    const row = block || {};
    const ok = row.ok === true;
    return `<div class="status-row" data-product="${esc(key)}" data-ok="${ok ? "1" : "0"}">
      ${pill(row.label || key, ok ? "ok" : "not_configured")}
      <span>${esc(row.detail || row.reason || "")}</span>
    </div>`;
  };

  const renderCoverage = (coverage) => {
    const google = ((coverage || {}).providers || {}).google_cse || {};
    const official = ((coverage || {}).providers || {}).official_feed || {};
    const status = google.status || "not_configured";
    const mode = coverage.data_mode || "empty";
    const live = coverage.live === true;
    const replay = coverage.recorded_replay === true || mode === "recorded_replay";
    const product = coverage.product_status || {};
    const sourceHealth = product.source_health || {};
    const evidence = product.evidence_sufficiency || {};
    const conclude = product.can_conclude || {};
    const modeLabel = live
      ? "正在使用官方实时来源"
      : replay
        ? "正在回放已记录的官方原文，不是当前最新事件"
        : mode === "empty"
          ? "等待官方源，当前没有演示数据"
          : "当前为测试/演示数据，不是生产实时事件";
    const bannerClass = live ? "is-live" : replay ? "is-replay" : "is-fixture";
    const healthOk = sourceHealth.ok === true;
    return {
      html: `<div class="event-coverage-inner" data-google-status="${esc(status)}" data-official-status="${esc(official.status || "idle")}" data-mode="${esc(mode)}" data-live="${live ? "1" : "0"}" data-replay="${replay ? "1" : "0"}" data-source-health="${healthOk ? "1" : "0"}">
        <div class="event-mode-banner ${bannerClass}" data-data-mode="${esc(mode)}">${esc(modeLabel)}</div>
        <div class="product-status">
          ${productRow("source_health", sourceHealth.ok == null ? { ok: healthOk, label: healthOk ? "数据源健康" : "数据源不完整", detail: "SEC / Fed / EIA 官方源" } : sourceHealth)}
          ${productRow("evidence_sufficiency", evidence.label ? evidence : { ok: false, label: "证据不足", detail: "尚未核对正文摘录" })}
          ${productRow("can_conclude", conclude.label ? conclude : { ok: false, label: "尚不能形成结论", reason: coverage.note || "证据不足" })}
        </div>
        ${providerPill(coverage, "sec_edgar")}
        ${providerPill(coverage, "federal_reserve")}
        ${providerPill(coverage, "eia_press")}
        <div class="subline">${esc(conclude.reason || coverage.note || "")} ${esc(evidence.detail || "摘录不支持是不形成方向的原因子集，三项不是互斥总数。")} 只影响事件观察，不影响价格、盈利或宏观利率。</div>
      </div>`,
      googleStatus: status,
      dataMode: mode
    };
  };

  const renderCard = (event, options = {}) => {
    const analysis = event.analysis || {};
    const why = options.why || event.why_relevant || "";
    const lanes = sourcesByLane(event.sources);
    const withheld = analysis.withheld || {};
    const conflicts = analysis.conflict_count || 0;
    const closed = analysis.closed_loop === true;
    const loopNote = closed
      ? ""
      : `<p class="subline" data-closed-loop="0" data-unsupported="${analysis.unsupported ? "1" : "0"}">证据不足，不形成方向。${esc(withheld.reason || "")} 只影响本事件，不影响价格、盈利或宏观利率。</p>`;
    return `<article class="event-card" data-event-id="${esc(event.event_id)}" data-event-type="${esc(event.event_type)}" data-event-status="${esc(event.status)}" data-conflict-count="${esc(conflicts)}" data-closed-loop="${closed ? "1" : "0"}">
      <header class="event-card-head">
        <h3>${esc(event.canonical_title)}</h3>
        <div class="event-meta">
          ${pill(event.event_type)}
          ${pill(`状态 ${event.status}`, event.status === "revoked" ? "invalid" : event.status)}
          ${pill(`严重度 ${event.severity}`)}
          ${pill(`范围 ${event.scope}`)}
          ${pill(`置信度 ${(analysis.confidence && analysis.confidence.text) || "—"}`, conflicts ? "conflict" : "")}
          ${pill(`documents ${analysis.document_count ?? (event.coverage && event.coverage.document_count) ?? (event.sources || []).length}`)}
          ${pill(`publishers ${analysis.publisher_count ?? (event.coverage && event.coverage.publisher_count) ?? "—"}`)}
          ${pill(`independent ${analysis.independent_publisher_count ?? (event.coverage && event.coverage.independent_publisher_count) ?? "—"}`)}
          ${pill(`superseded ${analysis.superseded_count ?? (event.coverage && event.coverage.superseded_count) ?? 0}`)}
        </div>
      </header>
      ${loopNote}
      ${answersHtml(event, why)}
      ${causalChainHtml(analysis)}
      ${why ? `<p class="why-relevant" data-why-relevant="1">为什么相关：${esc(why)}</p>` : ""}
      <div class="source-lane" data-lane="facts">
        <h4>${esc(laneLabel.official_fact)}</h4>
        ${lanes.official_fact.length ? lanes.official_fact.map(sourceRow).join("") : "<p class='subline'>无 Tier 1 原文</p>"}
      </div>
      <div class="source-lane" data-lane="media">
        <h4>${esc(laneLabel.media_report)}</h4>
        ${lanes.media_report.length ? lanes.media_report.map(sourceRow).join("") : "<p class='subline'>无通讯社确认</p>"}
      </div>
      <div class="source-lane" data-lane="opinion">
        <h4>${esc(laneLabel.research_opinion)}</h4>
        ${lanes.research_opinion.length ? lanes.research_opinion.map(sourceRow).join("") : "<p class='subline'>无机构观点</p>"}
      </div>
      ${timelineHtml(event.timeline)}
      ${claimsHtml(event.claims)}
      <div class="causal-block" data-analysis="1">
        <h4>已确认事实</h4>
        ${(analysis.confirmed_facts || []).map((row) => `<p>${esc(row.text)}<div class="evidence-refs">证据：${refsHtml(row.evidence_refs)}</div></p>`).join("") || "<p>withhold</p>"}
        <h4>与基线相比的变化</h4>
        <p>${boundHtml(analysis.change_vs_baseline)}</p>
        <h4>传导机制</h4>
        <p>${boundHtml(analysis.mechanism)}</p>
        <h4>受影响市场/行业</h4>
        <p>${esc((analysis.affected_markets || []).join(" / ") || "—")}</p>
        <h4>个股暴露</h4>
        ${exposuresHtml(analysis.exposures)}
        <h4>方向 / 期限</h4>
        <p data-direction="${esc((analysis.direction && analysis.direction.text) || withheld.direction || "withheld")}">${boundHtml(analysis.direction)} · ${boundHtml(analysis.horizon)}</p>
        <h4>置信度</h4>
        <p data-confidence-rule="${esc((analysis.confidence_rule && analysis.confidence_rule.result) || "")}">${boundHtml(analysis.confidence)}</p>
        <p class="subline" data-confidence-fields="1">规则：revoked=${esc((analysis.confidence_rule || {}).revoked)} · conflict_count=${esc((analysis.confidence_rule || {}).conflict_count)} · tier1=${esc((analysis.confidence_rule || {}).tier1_count)} · tier2=${esc((analysis.confidence_rule || {}).tier2_count)} → ${esc((analysis.confidence_rule || {}).result || "")}</p>
        <h4>反证 / 失效条件</h4>
        ${(analysis.counter_evidence || []).map((row) => `<p>${boundHtml(row)}</p>`).join("")}
        <h4>What changes</h4>
        <p data-what-changes="1">${boundHtml(analysis.what_changes)}</p>
        <p class="subline">方向状态：${esc(withheld.status || "withheld")} · ${esc(withheld.reason || "")}。禁止无来源数字或价格预测。</p>
      </div>
    </article>`;
  };

  const renderCenter = (payload) => {
    const events = payload.events || [];
    if (!events.length) {
      return `<div class="empty-note">新闻/事件为空只影响事件链，不影响价格、盈利或宏观利率链。</div>`;
    }
    return events.map((event) => renderCard(event)).join("");
  };

  const renderStock = (payload) => {
    const events = payload.events || [];
    const risk = payload.risk_state;
    const riskHtml = risk ? `<aside class="vix-risk" data-vix-role="${esc(risk.role)}">
      <strong>VIX 风险确认</strong>
      <span>${esc(risk.canonical_title || "")}</span>
      <div class="subline">${esc(risk.does_not_imply)}。${refsHtml(risk.evidence_refs)}</div>
    </aside>` : "";
    if (!events.length) {
      return `${riskHtml}<div class="empty-note" data-no-stock-events="1">该标的没有通过行业映射的重大事件。市场级事件只在事件中心完整展示，不会复制到所有股票。</div>`;
    }
    return riskHtml + events.map((event) => renderCard(event, { why: event.why_relevant })).join("");
  };

  window.StockPmEvents = {
    esc,
    safeUrl,
    sourceLink,
    renderCoverage,
    renderCard,
    renderCenter,
    renderStock
  };
})();
