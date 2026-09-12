(() => {
  "use strict";

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);

  const safeUrl = (value) => {
    try {
      const u = new URL(String(value), window.location.origin);
      return ["http:", "https:"].includes(u.protocol) ? u.href : "";
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
      ${href ? sourceLink(href, source.publisher || source.title) : `<span class="no-url">${esc(source.publisher || "无原文")}</span>`}
      <div class="news-meta">${esc(source.title || "")} · ${esc(source.published_at || "")}</div>
    </div>`;
  };

  const claimsHtml = (claims) => {
    if (!claims || !claims.length) return "";
    return `<div class="event-claims">${claims.map((claim) =>
      `<div class="claim-row" data-polarity="${esc(claim.polarity)}">${pill(claim.polarity, claim.polarity === "contradicts" ? "conflict" : "")} ${esc(claim.text)}</div>`
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

  const renderCoverage = (coverage) => {
    const google = ((coverage || {}).providers || {}).google_cse || {};
    const official = ((coverage || {}).providers || {}).official_feed || {};
    const status = google.status || "not_configured";
    return {
      html: `<div class="event-coverage-inner" data-google-status="${esc(status)}" data-official-status="${esc(official.status || "ok")}">
        ${pill(`coverage ${coverage.coverage || "partial"}`, coverage.coverage || "partial")}
        ${pill(`events ${coverage.status || "ok"}`, coverage.status || "ok")}
        ${pill(`google_cse ${status}`, status)}
        ${pill(`official_feed ${official.status || "ok"}`, official.status || "ok")}
        <span>last_success ${esc(coverage.last_success || "—")}</span>
        <span>source_count ${esc(coverage.source_count ?? 0)}</span>
        <span>conflict_count ${esc(coverage.conflict_count ?? 0)}</span>
        <span>reason_code ${esc(coverage.reason_code || "—")}</span>
        <div class="subline">只影响事件链：${esc(coverage.affects_chain || "events")}。不影响 ${esc((coverage.does_not_affect || []).join(" / ") || "price / earnings / macro_rates")}。Google 未配置时保持 not_configured，不抓取 HTML、不伪造结果。</div>
      </div>`,
      googleStatus: status
    };
  };

  const renderCard = (event, options = {}) => {
    const analysis = event.analysis || {};
    const why = options.why || event.why_relevant || "";
    const lanes = sourcesByLane(event.sources);
    const withheld = analysis.withheld || {};
    const conflicts = analysis.conflict_count || 0;
    return `<article class="event-card" data-event-id="${esc(event.event_id)}" data-event-type="${esc(event.event_type)}" data-event-status="${esc(event.status)}" data-conflict-count="${esc(conflicts)}">
      <header class="event-card-head">
        <h3>${esc(event.canonical_title)}</h3>
        <div class="event-meta">
          ${pill(event.event_type)}
          ${pill(`状态 ${event.status}`, event.status === "revoked" ? "invalid" : event.status)}
          ${pill(`严重度 ${event.severity}`)}
          ${pill(`范围 ${event.scope}`)}
          ${pill(`置信度 ${(analysis.confidence && analysis.confidence.text) || "—"}`, conflicts ? "conflict" : "")}
        </div>
      </header>
      ${answersHtml(event, why)}
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
        <p>${boundHtml(analysis.confidence)}</p>
        <h4>反证 / 失效条件</h4>
        ${(analysis.counter_evidence || []).map((row) => `<p>${boundHtml(row)}</p>`).join("")}
        <h4>What changes</h4>
        <p data-what-changes="1">${boundHtml(analysis.what_changes)}</p>
        <p class="subline">方向状态：${esc(withheld.status || "withheld")} · ${esc(withheld.reason || "")}。禁止无来源数字或价格预测。percent_forecast=${esc(analysis.percent_forecast)} price_target=${esc(analysis.price_target)}</p>
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
