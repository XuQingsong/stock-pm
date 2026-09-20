const TICKERS = ["AVGO", "LITE", "AAPL"];

function pathParts() {
  const parts = location.pathname.split("/").filter(Boolean);
  return {
    ticker: (parts[1] || "AVGO").toUpperCase(),
    kind: parts[2] || "",
    id: parts[3] || "",
  };
}

function fmt(metric) {
  if (!metric || metric.origin === "unavailable" || metric.value == null) return "unavailable";
  const n = metric.value;
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (Math.abs(n) >= 100) return String(Math.round(n * 100) / 100);
  return String(n);
}

function origin(metric) {
  return metric && metric.origin ? metric.origin : "";
}

function el(html) {
  const box = document.createElement("div");
  box.innerHTML = html.trim();
  return box.firstElementChild;
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderNav(ticker) {
  const nav = document.getElementById("ticker-nav");
  nav.innerHTML = TICKERS.map(
    (item) => `<a href="/brain/${item}" class="${item === ticker ? "on" : ""}">${item}</a>`
  ).join("");
}

function qualityBox(quality) {
  const axes = (quality && quality.axes) || {};
  const warnings = (quality && quality.warnings) || [];
  const poor = Object.values(axes).includes("Poor");
  const rows = Object.entries(axes)
    .map(([k, v]) => `<div class="q ${v}"><div class="k">${k.replaceAll("_", " ")}</div><b>${v}</b></div>`)
    .join("");
  const warns = warnings
    .map((item) => `<div><b>${item.axis || ""}:</b> ${item.reason || ""}</div>`)
    .join("");
  return `
    <div class="quality">${rows}</div>
    ${warnings.length ? `<div class="warnbox ${poor ? "poor" : ""}"><h3>BRAIN QUALITY WARNING</h3>${warns}</div>` : ""}
  `;
}

function evidenceLine(item) {
  if (!item) return "";
  const url = item.source_url
    ? `<a href="/brain/${pathParts().ticker}/evidence/${item.id}">${item.source || "source"} · ${item.source_time || ""}</a>`
    : `<span class="muted">${item.source || ""} · ${item.source_time || ""}</span>`;
  return `<div class="ev"><div>${escapeHtml(item.fact || item.excerpt || "")}</div>${url}</div>`;
}

function pill(text) {
  if (!text) return "";
  return `<span class="pill">${escapeHtml(text)}</span>`;
}

function emptyLine(text) {
  return `<p class="muted">${escapeHtml(text)}</p>`;
}

function evidenceBrief(item, fallback) {
  if (!item) return emptyLine(fallback);
  const href = item.id ? `/brain/${pathParts().ticker}/evidence/${item.id}` : "";
  const source = item.source ? `${item.source}${item.source_time ? " · " + item.source_time : ""}` : "";
  const body = escapeHtml(item.fact || item.reason || fallback);
  const meta = [item.strength, source].filter(Boolean).join(" · ");
  return `<div class="ev">${href ? `<a href="${href}">${body}</a>` : `<div>${body}</div>`}${
    meta ? `<div class="muted">${escapeHtml(meta)}</div>` : ""
  }</div>`;
}

function changeLine(change) {
  if (!change) return emptyLine("no later revision");
  const status =
    change.from_status || change.to_status
      ? `${change.from_status || "—"} → ${change.to_status || "—"}`
      : "";
  return `<div class="delta">${status ? `<b>${escapeHtml(status)}</b>` : ""}${
    change.reason ? `<div>${escapeHtml(change.reason)}</div>` : ""
  }<div class="muted">${escapeHtml(change.created_at || "")}</div></div>`;
}

function deltaBlock(item) {
  const fields = (item.deltas || [])
    .map(
      (delta) =>
        `<div class="delta-row"><span class="k">${escapeHtml(delta.field)}</span><span>${escapeHtml(
          delta.from == null || delta.from === "" ? "—" : delta.from
        )} → <b>${escapeHtml(delta.to == null || delta.to === "" ? "—" : delta.to)}</b></span></div>`
    )
    .join("");
  return `
    <div class="news">
      <div class="row">${pill(item.family)}${pill(item.label)}</div>
      ${fields}
      ${item.reason ? `<div class="muted">${escapeHtml(item.reason)}</div>` : ""}
    </div>`;
}

function nowBlock(chain) {
  const answers = (chain && chain.answers) || {};
  const blocks = [
    ["what_happened", "发生了什么", chain && chain.what_happened],
    ["why_it_affects_company", "为什么会影响公司", chain && chain.why_it_affects_company],
    ["path_to_driver_claim", "通过什么路径影响 Driver / Claim", chain && chain.path_to_driver_claim],
    ["what_market_is_trading", "市场现在怎么理解它", chain && chain.what_market_is_trading],
  ];
  return `
    <div class="now">
      ${blocks
        .map(([key, fallback, node]) => {
          const question = (node && node.question) || fallback;
          const answer = (node && node.answer) || answers[key] || "No persisted event yet.";
          return `<div class="now-q"><div class="k">${escapeHtml(question)}</div><p>${escapeHtml(answer)}</p></div>`;
        })
        .join("")}
    </div>`;
}

function marketBlock(market) {
  const expectations = (market && market.expectations) || [];
  const hyps = (market && market.active_hypotheses) || [];
  const unresolved = ((market && market.price_divergence) || {}).unresolved || [];
  return `
    <h3>Expectation</h3>
    ${
      expectations.length
        ? expectations
            .map(
              (row) => `
        <div class="card">
          <div class="row">${pill(row.comparison)}${pill(row.trend)}${pill(row.confidence)}</div>
          <h3>${escapeHtml(row.name || "Expectation")}</h3>
          <p>actual <b>${escapeHtml(row.actual == null ? "—" : row.actual)}</b> vs expected <b>${escapeHtml(
                row.expected == null ? "—" : row.expected
              )}</b></p>
          ${row.last_material_change ? `<p class="muted">${escapeHtml(row.last_material_change)}</p>` : ""}
          ${row.reason ? `<p>${escapeHtml(row.reason)}</p>` : ""}
        </div>`
            )
            .join("")
        : emptyLine("No persisted Expectation.")
    }
    <h3>Active Market Driver Hypotheses</h3>
    ${
      hyps.length
        ? hyps
            .map(
              (row) => `
        <div class="news">
          <div class="row">${pill(row.status)}${pill(row.confidence)}${pill(row.canonical_key)}</div>
          <div>${escapeHtml(row.hypothesis || "")}</div>
          ${row.reason ? `<div class="muted">${escapeHtml(row.reason)}</div>` : ""}
        </div>`
            )
            .join("")
        : emptyLine("No active Market Driver Hypothesis.")
    }
    <h3>Price Divergence / unresolved</h3>
    ${
      unresolved.length
        ? unresolved
            .map(
              (row) => `
        <div class="news">
          <div class="row">${pill(row.status)}${pill(row.explanation_grade)}${pill(row.direction)}</div>
          <div>${escapeHtml(row.unresolved_question || row.reason || "unresolved")}</div>
          <div class="muted">${escapeHtml(row.as_of || "")}${
                row.price_change_pct != null ? " · " + escapeHtml(row.price_change_pct) + "%" : ""
              }</div>
        </div>`
            )
            .join("")
        : emptyLine("No open price divergence.")
    }
  `;
}

function shownOf(shown, total, label) {
  if (total == null || shown == null || total <= shown) return "";
  return `<p class="muted">Showing ${shown} of ${total} persisted ${label}.</p>`;
}

function timeLabel(value) {
  if (!value) return "尚无记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未标明" : date.toLocaleString("zh-CN", { hour12: false });
}

const BAND_ZH = { very_high: "很高", high: "高", medium: "中", low: "低", unknown: "待验证" };
const CLAIM_ZH = {
  strongly_supported: "强支持", partially_supported: "部分支持", challenged: "受到挑战",
  contradicted: "已受反证", unverified: "待验证",
};
const band = (value) => BAND_ZH[value] || "待验证";

function claimEvidence(claim) {
  const parts = [];
  if (claim.strongest_support) {
    parts.push(`<div class="muted">Strongest support</div>${evidenceBrief(claim.strongest_support, "")}`);
  }
  if (claim.strongest_counter) {
    parts.push(`<div class="muted">Strongest counter</div>${evidenceBrief(claim.strongest_counter, "")}`);
  }
  if (claim.recent_change) {
    parts.push(`<div class="muted">Recent change</div>${changeLine(claim.recent_change)}`);
  }
  return parts.join("");
}

function renderPmView(data) {
  const claims = data.core_claims || [];
  const changed = data.what_changed || [];
  const questions = (data.open_research_questions || []).slice(0, 5);
  const market = data.market_environment || {};
  const drivers = market.dominant_drivers || [];
  const sensitivity = market.sensitivities || [];
  const freshness = data.freshness || {};
  const thesis = data.thesis || {};
  const attribution = data.price_attribution || {};
  const ready = data.brain_initialized === true;
  const driverById = Object.fromEntries(drivers.map((item) => [item.id, item]));
  document.title = `投资总览 · ${data.ticker}`;
  return `
    <div class="company-head">
      <p class="eyebrow">公司研究 / ${escapeHtml(data.ticker)}</p>
      <h1>${escapeHtml(data.company_name || data.ticker)}</h1>
      <p class="muted">Brain 更新：${escapeHtml(timeLabel(freshness.brain_run_at || data.as_of))} · 市场判断：${escapeHtml(timeLabel(freshness.market_updated_at))}</p>
    </div>
    ${ready ? "" : `<div class="warnbox"><strong>正式 Brain 基线尚未完成</strong><p>现有研究资料已落盘，但公司状态、价值驱动与核心判断尚未全部通过正式 Brain 验证。以下缺失处会如实显示。</p></div>`}
    <section id="investment-logic" class="lead-panel">
      <p class="eyebrow">当前投资逻辑</p>
      ${ready && !thesis.empty && thesis.current_thesis
        ? `<p class="thesis-text">${escapeHtml(thesis.current_thesis)}</p>${thesis.what_would_change_thesis ? `<p class="muted">需要重新评估的条件：${escapeHtml(thesis.what_would_change_thesis)}</p>` : ""}`
        : `<p class="muted">正式投资逻辑尚未形成。最近研究材料不能替代 Brain 的完整判断。</p>`}
    </section>
    <section id="core-claims">
      <div class="section-heading"><h2>基本面核心判断</h2><span>目标 3–5 条</span></div>
      <div class="cards">${ready && claims.length ? claims.slice(0, 5).map((claim) => `
        <article class="card">
          <div class="row">${pill(CLAIM_ZH[claim.status] || "待验证")}${pill(`可信度 ${band(claim.confidence)}`)}</div>
          <h3>${escapeHtml(claim.title || "未命名判断")}</h3>
          <p>${escapeHtml(claim.statement || "")}</p>
          ${claim.strongest_support ? `<div class="claim-evidence"><strong>主要支持</strong>${escapeHtml(claim.strongest_support.fact || "")}</div>` : `<p class="muted">支持证据尚未关联</p>`}
          ${claim.strongest_counter ? `<div class="claim-evidence"><strong>主要反证</strong>${escapeHtml(claim.strongest_counter.fact || "")}</div>` : ""}
          ${claim.claim_id ? `<a class="text-link" href="/brain/${escapeHtml(data.ticker)}/claims/${escapeHtml(claim.claim_id)}">查看判断依据 →</a>` : ""}
        </article>`).join("") : `<p class="empty-panel">尚无经过正式 Brain 选择的核心判断。</p>`}</div>
    </section>
    <section id="what-changed">
      <div class="section-heading"><h2>最近真正发生的变化</h2><span>只显示已有判断的实质修订</span></div>
      ${changed.length ? changed.slice(0, 5).map((row) => `<div class="change-item"><time>${escapeHtml(timeLabel(row.created_at))}</time><strong>${escapeHtml(row.label || "判断变化")}</strong><p>${escapeHtml(row.reason || "相关字段发生变化，原因尚未记录")}</p></div>`).join("") : `<p class="empty-panel">暂无已记录的实质判断变化。初次导入资料不计为变化。</p>`}
    </section>
    <section id="market-view">
      <div class="section-heading"><h2>当前市场变量对公司的影响</h2><a href="/market">查看市场总览 →</a></div>
      ${sensitivity.length ? `<div class="market-table-wrap"><table class="market-table"><thead><tr><th>市场变量</th><th>市场重要性</th><th>公司敏感度</th><th>当前相关性</th></tr></thead><tbody>${sensitivity.map((row) => {
        const driver = driverById[row.market_driver_id] || {};
        return `<tr><th>${escapeHtml(driver.display_name || driver.name || "未命名变量")}</th><td>待跨资产验证</td><td>${escapeHtml(band(row.sensitivity))}</td><td>${escapeHtml(band(row.current_relevance))}</td></tr>`;
      }).join("")}</tbody></table></div>` : `<p class="empty-panel">尚无经过结构性暴露验证的市场变量映射。</p>`}
      ${sensitivity.some((row) => !row.mechanism) ? `<p class="muted">部分传导机制尚未建立，敏感度不能视为已验证结论。</p>` : ""}
      <div class="price-panel"><h3>当前股价可能在交易什么</h3>
        <p>${escapeHtml(attribution.status || "尚无价格归因证据")}</p>
        ${attribution.status === "尚无价格归因证据" ? `<p class="muted">还没有价格反馈记录，暂不把市场变量当作已证实的股价原因。</p>` : `<p class="muted">这些是可并存的解释假设，未解释部分继续保留。</p>`}
      </div>
    </section>
    <section id="open-questions">
      <div class="section-heading"><h2>下一步最值得验证</h2><span>Top ${questions.length}</span></div>
      ${questions.length ? `<ol class="question-list">${questions.map((row) => `<li>${escapeHtml(row.question || "")}</li>`).join("")}</ol>` : `<p class="empty-panel">尚无待验证问题。</p>`}
    </section>
  `;
}

function renderHome(data) {
  const h = data.header || {};
  const g = h.growth || {};
  const v = h.valuation || {};
  const q = h.latest_quarter || {};
  const pm = data.pm || {};
  const claims = data.core_claims || [];
  const news = data.news || [];
  document.title = `Brain · ${data.ticker}`;
  return `
    <p class="muted">${data.ticker} · ${h.company_name || ""} · ${h.sector || ""}</p>
    <h1>${h.company_name || data.ticker}</h1>
    <div class="ident">
      <span>Price <b>${fmt(h.price)}</b> <span class="muted">${h.price_timestamp || ""} · ${origin(h.price)}</span></span>
      <span>Mkt cap <b>${fmt(h.market_cap)}</b></span>
      <span>PE TTM <b>${fmt(v.pe_ttm)}</b></span>
      <span>Fwd PE <b>${fmt(v.pe_forward)}</b> <span class="muted">${origin(v.pe_forward)}</span></span>
    </div>
    <div class="metrics">
      <div class="metric"><div class="k">TTM revenue</div><div class="v">${fmt(g.revenue_ttm)}</div></div>
      <div class="metric"><div class="k">Rev growth</div><div class="v">${fmt(g.revenue_growth_yoy)}</div></div>
      <div class="metric"><div class="k">TTM EPS</div><div class="v">${fmt(g.eps_ttm)}</div></div>
      <div class="metric"><div class="k">EPS growth</div><div class="v">${fmt(g.eps_growth_yoy)}</div></div>
    </div>
    <div class="ident">
      <span>Latest qtr rev <b>${fmt(q.revenue)}</b> YoY ${fmt(q.revenue_yoy)}</span>
      <span>EPS <b>${fmt(q.eps)}</b> YoY ${fmt(q.eps_yoy)}</span>
      <span>GM ${fmt(q.gross_margin)} / OM ${fmt(q.operating_margin)}</span>
      <span>FCF ${fmt(q.fcf)}</span>
    </div>
    ${qualityBox(data.quality)}
    <h2>Current Brain View</h2>
    <p class="view">${pm.current_view || "LLM view unavailable."}</p>
    <h2>Core Claims</h2>
    <div class="cards">
      ${
        claims.length
          ? claims
              .map(
                (claim) => `
        <article class="card">
          <div class="row">
            <span class="pill">${claim.status || ""}</span>
            <span class="pill">${claim.confidence || ""}</span>
            ${claim.changed ? `<span class="pill">changed</span>` : ""}
          </div>
          <h3>${claim.title || ""}</h3>
          <p>${claim.conclusion || claim.statement || ""}</p>
          <div class="muted">Support</div>
          ${(claim.support_evidence || []).map(evidenceLine).join("") || `<p class="muted">no grounded support</p>`}
          <div class="muted">Oppose</div>
          ${(claim.opposing_evidence || []).map(evidenceLine).join("") || `<p class="muted">none</p>`}
          <div class="muted">Gap</div>
          <p>${(claim.missing_evidence && claim.missing_evidence[0]) || "none stated"}</p>
          <a class="btn" href="/brain/${data.ticker}/claims/${claim.claim_id}">查看完整分析</a>
        </article>`
              )
              .join("")
          : `<p class="muted">No Core Claims. Brain will not invent them when LLM or evidence is insufficient.</p>`
      }
    </div>
    <h2>Past 30 days · Material</h2>
    ${
      news.length
        ? news
            .map(
              (item) => `
      <div class="news">
        <div><b>${item.title || item.new_fact || ""}</b></div>
        <div class="muted">${item.source || ""} → ${item.affected_claim_id || "no claim"} · ${item.impact || ""} · claim version ${item.claim_version_changed ? "yes" : "no"} · financial ${item.financial_impact || "unavailable"}</div>
        <div>${item.reason || item.new_fact || ""}</div>
      </div>`
            )
            .join("")
        : `<p class="muted">No material items (or news was not interpreted).</p>`
    }
    <h2>Short / Mid / Long</h2>
    <div class="horizons">
      <div><h3>Short 0–3M</h3><p>${pm.short_view || "unavailable"}</p></div>
      <div><h3>Mid 6–18M</h3><p>${pm.mid_view || "unavailable"}</p></div>
      <div><h3>Long 2–3Y</h3><p>${pm.long_view || "unavailable"}</p></div>
    </div>
  `;
}

function renderClaim(data, ticker) {
  const claim = data.claim || {};
  const r = data.reasoning || {};
  document.title = `Claim · ${claim.title || claim.claim_id}`;
  return `
    <a class="back" href="/brain/${ticker}">← ${ticker}</a>
    <h1>${claim.title || ""}</h1>
    <div class="row">
      <span class="pill">${claim.status || ""}</span>
      <span class="pill">${claim.confidence || ""}</span>
      <span class="pill">${claim.time_horizon || ""}</span>
    </div>
    <p class="view">${claim.statement || ""}</p>
    <p class="muted">${claim.why_it_matters || ""}</p>
    <h2>Support</h2>
    ${(data.support_evidence || []).map(evidenceLine).join("") || `<p class="muted">none</p>`}
    <h2>Oppose</h2>
    ${(data.opposing_evidence || []).map(evidenceLine).join("") || `<p class="muted">none</p>`}
    <h2>Evidence boundary</h2>
    <p>Proves: ${(r.evidence_boundary && r.evidence_boundary.proves) || ""}</p>
    <p>Does not prove: ${(r.evidence_boundary && r.evidence_boundary.does_not_prove) || ""}</p>
    <h2>Competing hypotheses</h2>
    ${(r.competing_hypotheses || []).map((item) => `<p>${item.statement || item} <span class="muted">${item.status || ""}</span></p>`).join("") || `<p class="muted">none</p>`}
    <h2>Missing / strengthen / weaken / invalidate</h2>
    <p>Missing: ${(r.missing_evidence || []).join("; ") || "none"}</p>
    <p>Strengthens: ${(r.what_strengthens || []).join("; ") || "none"}</p>
    <p>Weakens: ${(r.what_weakens || []).join("; ") || "none"}</p>
    <p>Invalidates: ${(r.what_invalidates || []).join("; ") || "none"}</p>
    <h2>Next research question</h2>
    <p>${r.next_research_question || ((data.questions || [])[0] && data.questions[0].question) || "none"}</p>
    <h2>Claim history</h2>
    ${(data.history || []).map((item) => `<div class="news">v${item.version} · ${item.status} · ${item.reason_for_change || ""} · ${item.created_at || ""}</div>`).join("") || `<p class="muted">v1 only</p>`}
    <h2>Related last-30-day news</h2>
    ${(data.news || []).map((item) => `<div class="news"><b>${item.title || ""}</b><div class="muted">${item.layer} · ${item.impact || ""}</div><div>${item.new_fact || item.reason || ""}</div></div>`).join("") || `<p class="muted">none</p>`}
  `;
}

function renderEvidence(data, ticker) {
  const ev = data.evidence || {};
  document.title = `Evidence · ${ev.id || ""}`;
  return `
    <a class="back" href="/brain/${ticker}">← ${ticker}</a>
    <h1>Evidence</h1>
    <p>${ev.fact || ""}</p>
    <p class="muted">${ev.excerpt || ""}</p>
    <p>Source: ${ev.source || ""} · ${ev.source_time || ""} · ${ev.source_type || ""} · ${ev.source_quality || ""}</p>
    <p>URL: ${ev.source_url ? `<a href="${ev.source_url}">${ev.source_url}</a>` : "none"}</p>
    <p>Family / independence: ${ev.evidence_family || ""} / ${ev.independence_key || ""}</p>
    <p>Proves: ${data.proves || "not stated"}</p>
    <p>Does not prove: ${data.does_not_prove || "not stated"}</p>
    <h2>Used by claims</h2>
    ${(data.used_by_claims || []).map((item) => `<p><a href="/brain/${ticker}/claims/${item.claim_id}">${item.title}</a> · ${item.direction}</p>`).join("") || `<p class="muted">none</p>`}
  `;
}

async function main() {
  const { ticker, kind, id } = pathParts();
  renderNav(ticker);
  const root = document.getElementById("root");
  const status = document.getElementById("br-status");
  try {
    if (kind === "claims" && id) {
      const res = await fetch(`/api/brain/${ticker}/claims/${id}`);
      const data = await res.json();
      if (!res.ok || !data.claim) {
        status.textContent = "missing";
        root.innerHTML = `<div class="warnbox poor"><h3>BRAIN QUALITY WARNING</h3><div>Claim ${id} was not found. Live Brain runs did not generate Core Claims (LLM not invoked).</div></div>`;
        document.title = `Claim missing · ${ticker}`;
        return;
      }
      status.textContent = data.claim.status || "claim";
      root.innerHTML = renderClaim(data, ticker);
      return;
    }
    if (kind === "evidence" && id) {
      const res = await fetch(`/api/brain/${ticker}/evidence/${id}`);
      const data = await res.json();
      if (!res.ok || !data.evidence) {
        status.textContent = "missing";
        root.innerHTML = `<div class="warnbox poor"><h3>BRAIN QUALITY WARNING</h3><div>Evidence ${id} was not found or has no provenance.</div></div>`;
        return;
      }
      status.textContent = "evidence";
      root.innerHTML = renderEvidence(data, ticker);
      return;
    }
    if (kind === "research") {
      const res = await fetch(`/api/brain/${ticker}`);
      const data = await res.json();
      status.textContent = data.status || "missing";
      root.innerHTML = renderHome(data);
      return;
    }
    const res = await fetch(`/api/brain/${ticker}/pm-view`);
    const data = await res.json();
    status.textContent = data.brain_initialized ? "判断已建立" : "基线待完成";
    root.innerHTML = renderPmView(data);
  } catch (err) {
    status.textContent = "error";
    root.innerHTML = `<div class="warnbox poor"><h3>BRAIN QUALITY WARNING</h3><div>${err}</div></div>`;
  }
}

main();
setInterval(() => {
  if (pathParts().kind === "") main();
}, 5 * 60 * 1000);
