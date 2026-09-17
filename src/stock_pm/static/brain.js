const TICKERS = ["AVGO", "AAPL", "LITE"];

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
  return `<div class="ev"><div>${item.fact || item.excerpt || ""}</div>${url}</div>`;
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
    const res = await fetch(`/api/brain/${ticker}`);
    const data = await res.json();
    status.textContent = data.status || "missing";
    root.innerHTML = renderHome(data);
  } catch (err) {
    status.textContent = "error";
    root.innerHTML = `<div class="warnbox poor"><h3>BRAIN QUALITY WARNING</h3><div>${err}</div></div>`;
  }
}

main();
