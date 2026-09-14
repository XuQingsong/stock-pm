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
    transmission: "Transmission · 传导渠道",
    impact: "Impact · 市场与暴露",
    what_changes: "What changes · 什么变了"
  };

  const LAYER_KIND_LABELS = {
    observable_fact: "可观察事实",
    derived_analysis: "派生分析",
    conditional_expectation: "条件预期"
  };

  const earningsPrintHtml = (row) => {
    if (!row) return "";
    const missing = [];
    if (row.actual == null) missing.push("actual");
    if (row.prior_year_actual == null) missing.push("prior");
    if (row.consensus == null) missing.push("consensus");
    if (!row.yoy && row.yoy !== 0) missing.push("yoy");
    if (!row.surprise && row.surprise !== 0) missing.push("surprise");
    const fmt = (value) => (value == null || value === "" ? "—" : esc(String(value)));
    const pct = (value) => (value == null || value === "" ? "—" : `${(Number(value) * 100).toFixed(2)}%`);
    const href = safeUrl(row.source_url);
    const binding = (name) => (row.field_bindings && row.field_bindings[name]) || {};
    const bindingHtml = (name, label) => {
      const item = binding(name);
      const src = safeUrl(item.source_url);
      return `<div class="subline" data-earnings-binding="${esc(name)}">字段 ${esc(label)} · ${esc(item.provider || "—")} / ${esc(item.function || "—")} / ${esc(item.raw_field || "—")} · as-of ${esc(item.as_of || "—")} · 抓取 ${esc(item.fetched_at || "—")} · ${esc(item.role || "—")}${src ? ` ${sourceLink(src, "字段来源")}` : " 无字段来源"}</div>`;
    };
    const implication = row.implication || "";
    const secMeta = row.sec_association || {};
    const secHref = safeUrl(secMeta.url);
    const lastSuccess = row.last_success_at || row.fetched_at || "";
    const nextRetry = row.next_retry_at || "";
    const namedMissing = (row.missing_fields || missing).filter(Boolean);
    const missingNote = namedMissing.length
      ? `<p class="subline" data-earnings-missing="${esc(namedMissing.join(","))}" data-last-success-at="${esc(lastSuccess)}" data-next-retry-at="${esc(nextRetry)}">本标的本链缺失字段：${esc(namedMissing.join(" / "))}。上次成功 ${esc(lastSuccess || "尚无")}。下次重试 ${esc(nextRetry || "下次调度")}。只降级本标的本财报链，不重复使用笼统的“数据不足”。</p>`
      : "";
    return `<section class="earnings-print" data-earnings-print="1" data-earnings-complete="${row.gap ? "0" : "1"}" data-earnings-gap="${esc(row.gap || "")}">
      <h4>结构化财报对照</h4>
      <div class="earnings-grid">
        <div data-earnings-field="actual"><span>Actual</span><b>${fmt(row.actual)}</b></div>
        <div data-earnings-field="prior"><span>Prior</span><b>${fmt(row.prior_year_actual)}</b></div>
        <div data-earnings-field="consensus"><span>Consensus</span><b>${fmt(row.consensus)}</b></div>
        <div data-earnings-field="yoy"><span>YoY</span><b>${pct(row.yoy)}</b></div>
        <div data-earnings-field="surprise"><span>Surprise</span><b>${pct(row.surprise)}</b></div>
        <div data-earnings-field="unit"><span>Unit / Currency</span><b>${esc(row.unit || "—")} · ${esc(row.currency || "—")}</b></div>
      </div>
      ${bindingHtml("actual", "Actual")}
      ${bindingHtml("prior_year_actual", "Prior")}
      ${bindingHtml("consensus", "Consensus")}
      <p class="subline" data-consensus-role="${esc(row.consensus_role || "")}">共识角色 ${esc(row.consensus_role || "—")}。EARNINGS_ESTIMATES 只作当前/未来修订快照，不回填历史 surprise。</p>
      <p class="subline">期间 ${esc(row.fiscal_period || "—")} · as-of ${esc(row.as_of || "—")} · 抓取 ${esc(row.fetched_at || "—")} · 规则 ${esc(row.rule_id || "—")}</p>
      <p class="subline">公式：${esc((row.yoy_inputs && row.yoy_inputs.formula) || "—")} ； ${esc((row.surprise_inputs && row.surprise_inputs.formula) || "—")}</p>
      ${href ? `<div class="evidence-refs">供应商来源：${sourceLink(href, row.provider || "earnings")}</div>` : "<p class='subline'>缺少可点击来源。</p>"}
      ${secHref ? `<p class="subline" data-sec-association="1">SEC 申报关联（未验证正文）：${sourceLink(secHref, "8-K metadata")}。同一日 8-K 不构成 EPS 证据。</p>` : secMeta.reason_code ? `<p class="subline" data-sec-association="1" data-sec-reason="${esc(secMeta.reason_code)}">SEC 申报未请求：${esc(secMeta.reason_code)}。不升级为官方证据。</p>` : ""}
      <p class="subline" data-earnings-implication="${esc(implication)}" data-price-direction="withheld">盈利含义 ${esc(implication || "未形成")} · 股价方向 withheld</p>
      ${missingNote}
      ${(row.transcript_excerpts || []).map((item) => `<p class="subline" data-transcript-excerpt="1">纪要 ${esc(item.quarter || "")} · ${esc(item.speaker || "")}：${esc(item.content || "")}${item.source_url ? ` <a class="source-link" href="${esc(item.source_url)}" target="_blank" rel="noopener noreferrer">原文</a>` : ""}</p>`).join("")}
    </section>`;
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
        if (layer.id === "change" && !(layer.text || "").trim() && (analysis.filing_fact_only || (analysis.evidence_gap && analysis.evidence_gap.primary_reason === "baseline_missing"))) {
          extra.push(`<div class="subline" data-baseline-missing="1">缺少可比较的当前值 vs 历史/consensus 基准，Change 未闭环。</div>`);
        }
        if (layer.id === "expectation") {
          const implication = (analysis.earnings_implication || {}).label || "";
          extra.push(`<div class="subline" data-price-direction="${esc(layer.direction || "withheld")}">市场/价格方向 ${esc(layer.direction || "withheld")} · 期限 ${esc(layer.horizon || "—")} · 置信度 ${esc(layer.confidence || "—")}</div>`);
          extra.push(`<div class="subline" data-earnings-implication="${esc(implication)}">盈利含义 ${esc(implication || "未形成")}（不是股价方向）</div>`);
        }
        if (layer.id === "impact") {
          extra.push(exposuresHtml(layer.exposures || analysis.exposures || []));
        }
        if (layer.id === "what_changes") {
          if (layer.invalidation) extra.push(`<div class="subline">失效：${esc(layer.invalidation)}</div>`);
          if (layer.follow_up) extra.push(`<div class="subline">后续观察：${esc(layer.follow_up)}</div>`);
        }
        return `<li class="event-causal-layer" data-causal-layer="1" data-layer="${esc(layer.id)}" data-layer-id="${esc(layer.layer_id || "")}" data-layer-kind="${esc(layer.layer_kind || "")}" data-cites="${esc(cites)}">
          <div class="chain-kicker">${esc(LAYER_LABELS[layer.id] || layer.id)}${layer.layer_kind ? ` · ${esc(LAYER_KIND_LABELS[layer.layer_kind] || layer.layer_kind)}` : ""}</div>
          <div data-layer-text="1">${esc((layer.text || "").trim() ? layer.text : "—")}</div>
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

  const cacheAgeLabel = (row) => {
    if (!row || !row.last_success_at) return "";
    if (row.cache_age_days != null && row.cache_age_days !== "") return `${row.cache_age_days}天`;
    const then = Date.parse(row.last_success_at);
    if (!Number.isFinite(then)) return "";
    return `${((Date.now() - then) / 86400000).toFixed(1)}天`;
  };

  const fieldHealthHtml = (fields) => {
    const rows = fields || {};
    return ["actual", "prior", "consensus", "transcript"].map((name) => {
      const row = rows[name] || {};
      const age = cacheAgeLabel(row);
      return `<div class="earnings-health-field" data-earnings-field-health="${esc(name)}" data-status="${esc(row.status || "")}" data-reason="${esc(row.reason_code || "")}" data-source="${esc(row.source || "")}" data-last-success-at="${esc(row.last_success_at || "")}" data-next-retry-at="${esc(row.next_retry_at || "")}" data-cache-age="${esc(age)}">
        <span>${esc(name)}</span>
        <b>${esc(row.status || "—")}</b>
        <div class="subline">${esc(row.reason_code || "ok")} · ${esc(row.source || "none")} · as-of ${esc(row.as_of || "—")} · 抓取 ${esc(row.fetched_at || "—")} · 新鲜度 ${esc(row.freshness || "—")} · 上次成功 ${esc(row.last_success_at || "—")} · 缓存年龄 ${esc(age || "—")} · 下次重试 ${esc(row.next_retry_at || "下次调度")}</div>
      </div>`;
    }).join("");
  };

  const endpointHealthHtml = (endpoints) => {
    const rows = endpoints || {};
    return ["EARNINGS", "EARNINGS_ESTIMATES", "EARNINGS_CALL_TRANSCRIPT"].map((name) => {
      const row = rows[name] || {};
      const age = cacheAgeLabel(row);
      return `<div class="earnings-health-endpoint" data-earnings-endpoint-health="${esc(name)}" data-status="${esc(row.status || "")}" data-source="${esc(row.source || "")}" data-freshness="${esc(row.freshness || "")}" data-last-success-at="${esc(row.last_success_at || "")}" data-next-retry-at="${esc(row.next_retry_at || "")}" data-cache-age="${esc(age)}">
        <span>${esc(name)}</span>
        <b>${esc(row.status || "—")}</b>
        <div class="subline">上次成功 ${esc(row.last_success_at || "尚无")} · 缓存年龄 ${esc(age || "—")} · 下次重试 ${esc(row.next_retry_at || "下次调度")} · ${esc(row.freshness || "—")} · ${esc(row.source || "none")}</div>
      </div>`;
    }).join("");
  };

  const endpointLine = (cover) => {
    const block = cover.endpoints || {};
    const now = block.this_round || {};
    const all = block.cumulative || {};
    const names = ["EARNINGS", "EARNINGS_ESTIMATES", "EARNINGS_CALL_TRANSCRIPT"];
    return names.map((name) => {
      const round = now[name] || {};
      const cum = all[name] || {};
      return `${name} 本轮 ${round.attempted ?? 0} / 累计 ${(cum.attempted_symbols || []).length}`;
    }).join(" · ");
  };

  const renderEarningsOverview = (cover) => {
    const row = cover || {};
    const live = row.live === true;
    const nextTask = (row.schedule && row.schedule.next_task) || {};
    const nextLabel = nextTask.symbol ? `${nextTask.symbol}:${nextTask.endpoint || ""}` : ((row.schedule && row.schedule.next_symbol) || "—");
    return `<section class="earnings-coverage" data-earnings-coverage="1" data-live="${live ? "1" : "0"}" data-class="${esc(row.data_class || "")}">
      <h4>财报覆盖 / 健康</h4>
      ${pill(`完整 ${row.complete_count ?? 0}`, "ok")}
      ${pill(`本轮 live ${row.fresh_live_complete_count ?? row.live_complete_count ?? 0}`, live ? "ok" : "")}
      ${pill(`cache/stale ${row.cache_stale_complete_count ?? 0}`)}
      ${pill(`部分 ${row.partial_count ?? 0}`)}
      ${pill(`延后 ${row.deferred_count ?? 0}`)}
      ${pill(`不支持 ${row.unsupported_count ?? 0}`, "not_configured")}
      ${pill(live ? "live-current" : "frozen/fixture", live ? "ok" : "not_configured")}
      <div class="subline" data-earnings-coverage-note="1">fixture 完整 ${esc(row.fixture_complete_count ?? 0)} · 本轮 fresh-live 完整 ${esc(row.fresh_live_complete_count ?? 0)} · cache/stale 完整 ${esc(row.cache_stale_complete_count ?? 0)}。${esc(row.note || "Fixture 成功不是上线覆盖。")} 预算 ${esc((row.budget && row.budget.used) ?? "—")}/${esc((row.budget && row.budget.max_calls) ?? "—")}。下次 ${esc(nextLabel)}。</div>
      <div class="subline" data-earnings-endpoint-coverage="1">${esc(endpointLine(row))}</div>
    </section>`;
  };

  const renderSymbolHealth = (health) => {
    if (!health || !health.symbol) return "";
    const missing = health.missing_fields || [];
    const age = cacheAgeLabel(health);
    return `<section class="earnings-symbol-health" data-earnings-symbol-health="1" data-symbol="${esc(health.symbol)}" data-supported="${health.supported === false ? "0" : "1"}" data-reason="${esc(health.reason_code || "")}" data-scenario="${esc(health.scenario || "")}" data-last-success-at="${esc(health.last_success_at || "")}" data-next-retry-at="${esc(health.next_retry_at || "")}" data-cache-age="${esc(age)}">
      <h4>${esc(health.symbol)} 财报状态</h4>
      ${pill(health.supported === false ? "unsupported" : (health.scenario || health.reason_code || "unknown"), health.supported === false ? "not_configured" : "ok")}
      <div class="subline">资产 ${esc(health.asset_class || "—")} · 来源 ${esc(health.source || "none")} · 上次成功 ${esc(health.last_success_at || "尚无")} · 缓存年龄 ${esc(age || "—")} · 下次重试 ${esc(health.next_retry_at || "下次调度")}${health.implication ? ` · 盈利含义 ${esc(health.implication)}` : ""}</div>
      ${missing.length ? `<p class="subline" data-earnings-missing="${esc(missing.join(","))}">本标的缺失：${esc(missing.join(" / "))}。不使用推测值填空。</p>` : ""}
      <div class="earnings-health-grid">${fieldHealthHtml(health.fields)}</div>
      <div class="earnings-health-endpoints">${endpointHealthHtml(health.endpoints)}</div>
    </section>`;
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
        ${providerPill(coverage, "alpha_vantage_earnings")}
        ${renderEarningsOverview(coverage.earnings_coverage || {})}
        <div class="subline">${esc(conclude.reason || coverage.note || "")} ${esc(evidence.detail || "摘录不支持是不形成方向的原因子集，三项不是互斥总数。")} 只影响事件观察，不影响价格、盈利或宏观利率。宏观信息不复制到全部个股。</div>
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
    const gap = analysis.evidence_gap || {};
    const conflicts = analysis.conflict_count || 0;
    const closed = analysis.closed_loop === true;
    const lastFetch = withheld.last_fetched_at || gap.last_fetched_at || "";
    const lastSuccess = (analysis.earnings_evidence || {}).last_success_at || gap.last_success_at || lastFetch;
    const nextRetry = (analysis.earnings_evidence || {}).next_retry_at || gap.next_retry_at || "";
    const reasonCode = withheld.primary_reason || gap.primary_reason || "";
    const fetchNote = lastSuccess
      ? ` 上次成功：${esc(lastSuccess)}。${nextRetry ? `下次重试：${esc(nextRetry)}。` : ""}`
      : " 暂无成功抓取记录。";
    const filingItems = [...new Set((event.sources || []).flatMap((row) => row.filing_items || []))];
    const filingNote = filingItems.length
      ? `<p class="subline" data-filing-items="1">申报栏目（发现/元数据，不是正文事实）：${esc(filingItems.join("；"))}</p>`
      : "";
    const earnings = analysis.earnings_evidence || null;
    const earningsHtml = earningsPrintHtml(earnings);
    const factOnly = analysis.filing_fact_only === true || reasonCode === "baseline_missing";
    const loopNote = closed
      ? ""
      : factOnly
        ? `<p class="subline" data-closed-loop="0" data-filing-fact-only="1" data-unsupported="${analysis.unsupported ? "1" : "0"}" data-withhold-reason="${esc(reasonCode || "baseline_missing")}" data-last-fetch-at="${esc(lastFetch)}">已获得官方正文事实；缺少可比较基准/传导规则，因此不形成方向。${reasonCode ? ` 缺失原因：${esc(reasonCode)}。` : ""}${fetchNote} 当前仅作为事实展示；在基准与传导规则补齐前，不纳入方向判断，也不影响其他事件的正常分析。</p>`
        : `<p class="subline" data-closed-loop="0" data-unsupported="${analysis.unsupported ? "1" : "0"}" data-withhold-reason="${esc(reasonCode)}" data-last-fetch-at="${esc(lastFetch)}" data-last-success-at="${esc(lastSuccess)}" data-next-retry-at="${esc(nextRetry)}">${reasonCode ? `本链不能形成完整结论，缺 ${esc(reasonCode)}。` : "本链不能形成完整结论。"}${esc(withheld.reason || "")}${fetchNote} 本事件不形成方向，也不阻断其他事件的正常分析。</p>`;
    return `<article class="event-card" data-event-id="${esc(event.event_id)}" data-event-type="${esc(event.event_type)}" data-event-status="${esc(event.status)}" data-conflict-count="${esc(conflicts)}" data-closed-loop="${closed ? "1" : "0"}" data-filing-fact-only="${factOnly ? "1" : "0"}" data-can-form-direction="${analysis.can_form_direction === true ? "1" : "0"}">
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
      ${filingNote}
      ${earningsHtml}
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

  const macroChainHtml = (chain, options = {}) => {
    const layers = (chain && chain.layers) || [];
    if (!layers.length) return "";
    const why = options.why || chain.why_relevant || "";
    const counters = chain.counter_evidence || [];
    const what = chain.what_changes || {};
    return `<article class="macro-chain" data-macro-chain="1" data-chain-id="${esc(chain.chain_id || "")}" data-metric="${esc(chain.metric || "")}" data-status="${esc(chain.status || "")}" data-data-class="${esc(chain.data_class || "")}" data-can-form-direction="${chain.can_form_direction === true ? "1" : "0"}" data-vix-role="${esc(chain.vix_role || "")}">
      <div class="event-meta">
        ${pill(chain.metric || chain.family || "macro")}
        ${pill(chain.status || "ok", chain.status === "ok" ? "ok" : "not_configured")}
        ${pill(chain.data_class === "live_current" ? "live-current" : (chain.data_class || "frozen/fixture"), chain.data_class === "live_current" ? "ok" : "not_configured")}
        ${pill(`chain ${chain.chain_id || ""}`)}
      </div>
      ${chain.degrade_detail ? `<p class="subline" data-macro-degraded="1" data-degrade-reason="${esc(chain.degrade_reason || "")}">本链降级：${esc(chain.degrade_detail)}</p>` : ""}
      <ol class="event-causal-chain" data-macro-layers="1">
        ${layers.map((layer) => {
          const extra = [];
          if (layer.id === "transmission" && (layer.channels || []).length) {
            extra.push(`<div class="subline" data-transmission="1">${esc((layer.channels || []).join(" / "))}</div>`);
          }
          if (layer.id === "impact") extra.push(exposuresHtml(layer.exposures || chain.exposures || []));
          if (layer.id === "what_changes") {
            (layer.follow_ups || what.follow_ups || []).forEach((item) => extra.push(`<div class="subline" data-follow-up="1">${esc(item)}</div>`));
            if (layer.invalidation || what.invalidation) extra.push(`<div class="subline" data-invalidation="1">失效：${esc(layer.invalidation || what.invalidation)}</div>`);
          }
          if (layer.id === "expectation") {
            extra.push(`<div class="subline" data-layer-kind="conditional_expectation">条件预期，不是确定事实 · 置信度 ${esc(layer.confidence || chain.confidence || "—")}</div>`);
          }
          return `<li class="event-causal-layer" data-causal-layer="1" data-layer="${esc(layer.id)}" data-layer-id="${esc(layer.layer_id || "")}" data-layer-kind="${esc(layer.layer_kind || "")}" data-cites="${esc((layer.cites || []).join(" "))}">
            <div class="chain-kicker">${esc(LAYER_LABELS[layer.id] || layer.id)} · ${esc(LAYER_KIND_LABELS[layer.layer_kind] || layer.layer_kind || "")}</div>
            <div data-layer-text="1">${esc(layer.text || "—")}</div>
            ${layer.evidence_refs && layer.evidence_refs.length ? `<div class="evidence-refs" data-evidence-refs="1">证据：${refsHtml(layer.evidence_refs)}</div>` : ""}
            ${extra.join("")}
          </li>`;
        }).join("")}
      </ol>
      ${why ? `<p class="why-relevant" data-why-relevant="1" data-exposure-reason="1">为什么与本公司相关：${esc(why)}</p>` : ""}
      ${counters.length ? `<div data-counter-evidence="1">${counters.map((row) => `<p class="subline">${boundHtml(row)}</p>`).join("")}</div>` : ""}
      <p class="subline" data-what-changes="1">${esc(what.text || "")}</p>
    </article>`;
  };

  const renderMacroSummary = (payload) => {
    const summary = payload.macro_driver_summary || {};
    const chains = payload.macro_chains || [];
    if (!chains.length && !summary.count) return "";
    return `<section class="macro-driver-summary" data-macro-driver-summary="1" data-ok="${esc(summary.ok_count ?? 0)}" data-degraded="${esc(summary.degraded_count ?? 0)}">
      <h3>宏观驱动摘要</h3>
      <div class="subline">${esc(summary.note || "")} live-current ${esc(summary.live_current_count ?? 0)} · frozen ${esc(summary.frozen_count ?? 0)} · 降级 ${esc(summary.degraded_count ?? 0)}</div>
      ${(summary.headlines || []).map((row) => `<div class="subline" data-macro-headline="${esc(row.chain_id || "")}">${esc(row.metric || "")} · ${esc(row.text || "")}</div>`).join("")}
      ${chains.map((chain) => `<details class="macro-chain-expand" data-chain-id="${esc(chain.chain_id || "")}" ${chain.status === "degraded" ? "open" : ""}><summary>${esc(chain.metric || chain.family || "macro")} · ${esc(chain.status || "")} · ${esc(chain.chain_id || "")}</summary>${macroChainHtml(chain)}</details>`).join("")}
    </section>`;
  };

  const renderCenter = (payload) => {
    const events = payload.events || [];
    const summary = renderMacroSummary(payload);
    if (!events.length && !summary) {
      return `<div class="empty-note">新闻/事件为空只影响事件链，不影响价格、盈利或宏观利率链。</div>`;
    }
    return summary + events.map((event) => renderCard(event)).join("");
  };

  const renderStock = (payload) => {
    const events = payload.events || [];
    const risk = payload.risk_state;
    const healthHtml = renderSymbolHealth(payload.earnings_health || {});
    const mapped = payload.macro_chains || [];
    const mappedHtml = mapped.length ? `<section data-stock-macro-chains="1">${mapped.map((chain) => macroChainHtml(chain, { why: chain.why_relevant })).join("")}</section>` : "";
    const riskHtml = risk ? `<aside class="vix-risk" data-vix-role="${esc(risk.role)}" data-chain-id="${esc(risk.chain_id || "")}" data-can-form-direction="0">
      <strong>VIX 风险确认</strong>
      <span>${esc(risk.canonical_title || "")}</span>
      <div class="subline">${esc(risk.does_not_imply)}。不得把 VIX 写成个股涨跌。${refsHtml(risk.evidence_refs)}</div>
      ${(risk.counter_evidence || []).map((row) => `<div class="subline" data-counter-evidence="1">${boundHtml(row)}</div>`).join("")}
    </aside>` : "";
    if (!events.length && !mapped.length) {
      return `${healthHtml}${riskHtml}<div class="empty-note" data-no-stock-events="1">该标的没有通过行业映射的重大事件。市场级事件只在事件中心完整展示，不会复制到所有股票。</div>`;
    }
    return healthHtml + riskHtml + mappedHtml + events.map((event) => renderCard(event, { why: event.why_relevant })).join("");
  };

  window.StockPmEvents = {
    esc,
    safeUrl,
    sourceLink,
    renderCoverage,
    renderCard,
    renderCenter,
    renderStock,
    renderMacroSummary
  };
})();
