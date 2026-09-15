(() => {
  "use strict";

  const DEFAULTS = ["AVGO", "COHR", "XOM"];

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));

  const miss = (value) => {
    if (value === null || value === undefined || value === "" || value === "Missing") {
      return '<span class="muted">Missing / Unresolved</span>';
    }
    return esc(value);
  };

  const pct = (value) => {
    if (value === null || value === undefined || value === "") return "Missing";
    const n = Number(value);
    if (Number.isNaN(n)) return String(value);
    return `${Math.round(n * 100)}%`;
  };

  const money = (value) => {
    if (value === null || value === undefined || value === "") return "Missing";
    const n = Number(value);
    if (Number.isNaN(n)) return String(value);
    if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
    if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
    return String(n);
  };

  const outcomeLabel = (value) => {
    const raw = String(value || "unscored").toLowerCase();
    if (raw === "missed") return "miss";
    return raw;
  };

  const pill = (text, kind) => `<span class="pill ${esc(kind || text || "")}">${esc(text || "unresolved")}</span>`;

  const sourceLink = (row) => {
    if (row && row.source_url) {
      return `<a href="${esc(row.source_url)}" target="_blank" rel="noreferrer">${esc(row.source || "source")}</a>`;
    }
    if (row && (row.source || row.source_time)) return esc(row.source || "");
    return '<span class="unverified">UNVERIFIED</span>';
  };

  const clip = (value, limit = 240) => {
    const text = String(value ?? "");
    if (!text || text === "Missing") return miss(value);
    if (text.length <= limit) return esc(text);
    return `<details class="ev clip"><summary>${esc(text.slice(0, limit))}…</summary><p>${esc(text)}</p></details>`;
  };

  const tickerFromPath = () => {
    const parts = location.pathname.split("/").filter(Boolean);
    return (parts[1] || "AVGO").toUpperCase();
  };

  const evidenceBlock = (rows, label) => {
    const list = rows || [];
    if (!list.length) return `<p class="missing">${esc(label || "Evidence")}: Missing / Unresolved</p>`;
    return `<details class="ev"><summary>${esc(label || "Evidence")} (${list.length})</summary>${
      list.map((row) => {
        const url = row.source_url
          ? `<a href="${esc(row.source_url)}" target="_blank" rel="noreferrer">source</a>`
          : '<span class="unverified">UNVERIFIED</span>';
        return `<p><b>${esc(row.fact || "Missing")}</b><br><span class="muted">${esc(row.source || "")} · ${esc(row.source_time || "")} · ${url}</span>${
          row.excerpt && row.excerpt !== row.fact ? `<br>${esc(row.excerpt)}` : ""
        }${row.reason ? `<br><span class="muted">${esc(row.reason)}</span>` : ""}</p>`;
      }).join("")
    }</details>`;
  };

  function render(data) {
    const hero = data.hero || {};
    const cases = data.cases || {};
    const tree = data.assumption_tree || {};
    const delivery = data.delivery_history || {};
    const customer = data.customer_side || {};
    const bridge = data.revenue_bridge || {};
    const chain = data.causal_chain || {};
    const implied = data.market_implied || {};
    const reaction = data.market_reaction || {};
    const valuation = data.valuation || {};
    const missing = (data.missing || []).map((item) => esc(item)).join(" · ") || "none listed";

    const caseCell = (name, row) => {
      const c = row || {};
      return `<div class="cell"><span>${esc(name)}</span><b>${miss(c.target)}</b>
        <div class="muted">g ${miss(c.growth_display || pct(c.growth))} · m ${miss(c.multiple)} · EPS ${miss(c.eps)}</div>
        <div class="muted">${esc(c.origin || "")}</div></div>`;
    };

    const treeHtml = (tree.branches || []).map((branch) => {
      const nodes = (branch.nodes || []).map((node) => {
        return `<details class="node" data-node="${esc(node.assumption_id || "")}">
          <summary><b>${esc(node.statement || "Missing")}</b><br>
            ${pill(node.status, node.status)} ${pill(node.thesis_role, node.thesis_role)}
            <span class="counts">conf ${miss(node.confidence)} · support ${node.supporting_count ?? 0} · oppose ${node.opposing_count ?? 0} · unresolved ${node.unresolved_count ?? 0}</span>
          </summary>
          ${evidenceBlock(node.supporting, "Supporting")}
          ${evidenceBlock(node.opposing, "Opposing")}
          <p class="muted">Next verification: ${miss(node.next_verification)}</p>
          <p class="muted">Invalidation: ${miss(node.invalidation)}</p>
          ${(node.unresolved || []).length ? `<p class="muted">Unresolved: ${esc((node.unresolved || []).join("; "))}</p>` : ""}
        </details>`;
      }).join("") || `<p class="missing">No assumptions in this branch.</p>`;
      return `<div><h3>${esc(branch.id)}. ${esc(branch.title)}</h3>${nodes}</div>`;
    }).join("");

    const ledger = (data.commitment_ledger || []).map((row) => `<tr>
      <td>${esc(row.commitment || "Missing")}${row.trace === "UNVERIFIED" ? ' <span class="unverified">UNVERIFIED</span>' : ""}</td>
      <td>${miss(row.date)}</td>
      <td>${sourceLink(row)}</td>
      <td>${miss(row.time_horizon)}</td>
      <td>${miss(row.metric)}</td>
      <td>${miss(row.stated_value_or_range)}</td>
      <td>${pill(row.status || row.current_status, row.status || row.current_status)}</td>
      <td>${pill(row.delivery_status || row.status, row.delivery_status || row.status)}</td>
      <td>${miss(row.next_check)}</td>
    </tr>`).join("") || `<tr><td colspan="9" class="muted">Missing / Unresolved</td></tr>`;

    const hist = (delivery.history || []).map((row) => {
      const g = row.guidance || {};
      const a = row.actual || {};
      return `<tr>
        <td>${esc(row.quarter || row.period || "Missing")}</td>
        <td>${esc(g.kind || "insufficient_data")}${g.eps_estimate != null ? ` · EPS est ${esc(g.eps_estimate)}` : ""}${g.company_text ? `<div class="muted">${esc(g.company_text)}</div>` : ""}</td>
        <td>${a.eps != null ? `EPS ${esc(a.eps)}` : "Missing"}${a.revenue != null ? `<div class="muted">rev ${money(a.revenue)}</div>` : ""}</td>
        <td>${pill(outcomeLabel(row.outcome), outcomeLabel(row.outcome))}</td>
        <td>${row.guidance_revision && row.guidance_revision !== "unchanged" ? pill("revised", "revised") + ` ${esc(row.guidance_revision)}` : "—"}</td>
        <td>${miss(row.source)}</td>
      </tr>`;
    }).join("") || `<tr><td colspan="6" class="muted">Missing / Unresolved</td></tr>`;

    const chainHtml = (chain.layers || []).map((layer, idx, arr) => {
      const weak = layer.weakest ? " weak" : "";
      return `<div class="layer">
        <div class="rail"><i class="dot"></i>${idx < arr.length - 1 ? '<i class="line"></i>' : ""}</div>
        <div class="layer-body${weak}">
          <b>${esc(layer.label || layer.layer)}</b>
          ${layer.weakest ? " " + pill("weakest layer", "weak") : ""}
          <div class="muted">confidence ${miss(layer.confidence)} · family ${miss(layer.evidence_family)} · bottleneck ${layer.bottleneck ? "yes" : "no"}</div>
          <div class="muted">unresolved: ${esc((layer.unresolved || []).join("; ") || "none")}</div>
          ${evidenceBlock(layer.evidence, "Layer evidence")}
        </div>
      </div>`;
    }).join("") || `<p class="missing">Causal chain Missing / Unresolved</p>`;

    const bridgeHtml = [`<div class="layer-body"><span class="kicker">Current revenue</span><b>${money(bridge.current_revenue)}</b><div class="muted">${esc(bridge.mode || "")} · ${esc(bridge.origin || "")}</div></div>`]
      .concat((bridge.lines || []).map((line) => `<div class="layer-body"><span class="kicker">${esc(line.label || line.family || "unknown / missing")}</span><b>${line.latest_print_revenue != null ? money(line.latest_print_revenue) : "Missing / estimated"}</b><div class="muted">${esc(line.origin || "")}${line.share != null ? ` · share ${esc(line.share)}` : ""}</div></div>`))
      .join('<div class="muted" style="margin:2px 8px">↓</div>');

    const sens = (implied.sensitivity || []).map((row) => `<tr>
      <td>${esc(row.multiple)}${row.is_base_multiple ? " (base)" : ""}</td>
      <td>${miss(row.implied_forward_eps)}</td>
      <td>${miss(row.implied_2y_eps_cagr_display || pct(row.implied_2y_eps_cagr))}</td>
    </tr>`).join("") || `<tr><td colspan="3" class="muted">Missing / Unresolved</td></tr>`;

    const group = (title, rows) => `<div class="cell"><h3>${esc(title)}</h3>${
      (rows || []).length
        ? rows.map((row) => `<div><p>${esc(row.text || "")} ${row.trace === "UNVERIFIED" ? '<span class="unverified">UNVERIFIED</span>' : ""}</p>${evidenceBlock(row.evidence, "Evidence")}</div>`).join("")
        : '<p class="missing">Missing / Unresolved</p>'
    }</div>`;

    const monitors = (data.monitoring || []).map((row) => `<div class="cell">
      <b>${esc(row.item || "Missing")}</b>
      <p>Current: ${miss(row.current_state)}</p>
      <p>Next check: ${miss(row.next_check)}</p>
      <p class="muted">Strengthen: ${miss(row.strengthen)}</p>
      <p class="muted">Weaken: ${miss(row.weaken)}</p>
      <p class="muted">Break: ${miss(row.break_condition || row.break)}</p>
    </div>`).join("") || `<p class="missing">Monitoring Missing / Unresolved</p>`;

    const versions = (data.thesis_history || []).map((row) => `<details class="node">
      <summary><b>v${esc(row.version)}</b> · ${esc(row.what_changed || "")} · conf ${miss(row.confidence)}</summary>
      <p>${esc(row.core_thesis || "")}</p>
      <p class="muted">Assumptions strengthened: ${esc((row.strengthened_assumptions || []).join(", ") || "none")} · weakened: ${esc((row.weakened_assumptions || []).join(", ") || "none")}</p>
      <p class="muted">Valuation: ${esc(JSON.stringify(row.valuation_change || "n/a"))}</p>
      <p class="muted">Confidence change: ${esc(JSON.stringify(row.confidence_change || "n/a"))}</p>
    </details>`).join("") || `<p class="missing">Thesis history Missing / Unresolved</p>`;

    const valRow = (label, key) => {
      const b = cases.bear || {};
      const m = cases.market_implied || {};
      const ba = cases.base || {};
      const bu = cases.bull || {};
      const pick = (row) => row[key];
      return `<tr><th>${esc(label)}</th><td>${miss(pick(b))}</td><td>${miss(pick(m))}</td><td>${miss(pick(ba))}</td><td>${miss(pick(bu))}</td></tr>`;
    };

    document.getElementById("root").innerHTML = `
      <section id="hero">
        <div class="kicker">${esc(data.legal_name || data.ticker)} · ${esc(data.template_id || "")}</div>
        <h1>Core thesis</h1>
        <p class="thesis">${miss(hero.core_thesis)}</p>
        ${hero.core_thesis_full && hero.core_thesis_full !== hero.core_thesis ? `<details class="ev"><summary>Full stored thesis</summary><p>${esc(hero.core_thesis_full)}</p></details>` : ""}
        <div class="banner">
          <div>Direct issuer cross-check: <span class="${hero.customer_direct ? "yes" : "zero"}">${esc(hero.customer_direct ?? "Missing")}</span></div>
          <div>Category cross-check: <span class="${hero.customer_category ? "yes" : "zero"}">${esc(hero.customer_category ?? "Missing")}</span></div>
          <div>Industry demand confirmation: <span class="${hero.industry_demand ? "yes" : "zero"}">${hero.industry_demand ? "有" : "无"}</span></div>
        </div>
        <div class="grid g4">
          <div class="cell"><span>Thesis confidence</span><b>${miss(hero.confidence)}</b></div>
          <div class="cell"><span>Valuation status</span><b>${pill(hero.valuation_status, hero.valuation_status)}</b>
            ${(hero.why_provisional || []).length ? `<div class="muted">because ${(hero.why_provisional || []).map(esc).join("; ")}</div>` : ""}
            ${(valuation.why_provisional || []).length && !(hero.why_provisional || []).length ? `<div class="muted">because ${(valuation.why_provisional || []).map(esc).join("; ")}</div>` : ""}
          </div>
          <div class="cell"><span>Weakest causal layer</span><b>${miss(hero.weakest_layer)}</b></div>
          <div class="cell"><span>Spot</span><b>${hero.spot != null ? esc(Number(hero.spot).toFixed(2)) : miss(hero.spot)}</b></div>
        </div>
        <div class="views">
          <div><span class="kicker">Short</span><p>${clip(hero.short_term_view)}</p></div>
          <div><span class="kicker">Mid</span><p>${clip(hero.mid_term_view)}</p></div>
          <div><span class="kicker">Long</span><p>${clip(hero.long_term_view)}</p></div>
        </div>
        <div class="grid g4" id="hero-cases">
          ${caseCell("Bear", cases.bear)}
          ${caseCell("Market-implied", cases.market_implied)}
          ${caseCell("Base", cases.base)}
          ${caseCell("Bull", cases.bull)}
        </div>
        <div class="grid g3" style="margin-top:10px">
          <div class="cell"><span>Strongest assumption</span><b>${miss((hero.strongest_assumption || {}).statement)}</b><div class="muted">${esc((hero.strongest_assumption || {}).status || "")}</div></div>
          <div class="cell highlight"><span>Weakest assumption</span><b>${miss((hero.weakest_assumption || {}).statement)}</b><div class="muted">${esc(((hero.weakest_assumption || {}).unresolved || []).join("; "))}</div></div>
          <div class="cell"><span>Biggest unresolved gap</span><b>${miss(hero.biggest_unresolved_gap)}</b></div>
        </div>
        <div class="cell" style="margin-top:10px">
          <span>Most important assumptions</span>
          <ol class="top3">${
            (hero.top_assumptions || []).length
              ? (hero.top_assumptions || []).slice(0, 3).map((row) => `<li>${esc(row.statement || "Missing")} <span class="muted">${esc(row.status || "")} · ${esc(row.role || "")}</span></li>`).join("")
              : "<li class='muted'>Missing / Unresolved</li>"
          }</ol>
        </div>
      </section>

      <section id="tree">
        <h2>Assumption tree</h2>
        <p class="sub">Core thesis: ${miss(hero.core_thesis)}</p>
        <div class="grid g2">${treeHtml}</div>
      </section>

      <section id="ledger">
        <h2>Commitment ledger</h2>
        <table><thead><tr><th>Commitment</th><th>Date</th><th>Source</th><th>Horizon</th><th>Metric</th><th>Value / range</th><th>Status</th><th>Delivery</th><th>Next check</th></tr></thead><tbody>${ledger}</tbody></table>
      </section>

      <section id="delivery">
        <h2>Management delivery history</h2>
        <p>Scored: ${esc((delivery.scored_quarters || []).join(", ") || "none")} · Unscored: ${esc((delivery.unscored_quarters || []).join(", ") || "none")}</p>
        <p class="muted">${esc(delivery.credibility || delivery.summary || "")}</p>
        <table><thead><tr><th>Quarter</th><th>Guidance</th><th>Actual</th><th>Outcome</th><th>Revision</th><th>Source</th></tr></thead><tbody>${hist}</tbody></table>
      </section>

      <section id="customer">
        <h2>Customer-side validation</h2>
        <div class="banner">
          <div>Direct issuer cross-check: <span class="${customer.direct_issuer_cross_check ? "yes" : "zero"}">${esc(customer.direct_issuer_cross_check ?? "Missing")}</span></div>
          <div>Category cross-check: <span class="${customer.category_cross_check ? "yes" : "zero"}">${esc(customer.category_cross_check ?? "Missing")}</span></div>
          <div>Industry demand confirmation: <span class="${customer.industry_demand_confirmation ? "yes" : "zero"}">${customer.industry_demand_confirmation ? "有" : "无"}</span></div>
        </div>
        <p>${miss(customer.conclusion)}</p>
        <p class="muted">Industry demand can be real without confirming a named contract with ${esc(data.ticker)}.</p>
        <div class="grid g3">
          <div class="cell"><h3>Issuer claims</h3>${evidenceBlock(customer.issuer_management, "Issuer")}</div>
          <div class="cell"><h3>Independent customer</h3>${evidenceBlock(customer.independent_customer, "Customer")} ${evidenceBlock(customer.industry_demand_only, "Industry-demand only")}</div>
          <div class="cell"><h3>Industry third-party</h3>${evidenceBlock(customer.industry_third_party, "Industry")}</div>
        </div>
      </section>

      <section id="bridge">
        <h2>Revenue bridge</h2>
        ${bridge.mode === "top_down_range" || bridge.origin === "estimated" ? '<p class="missing">top_down_range / estimated — official segment mix missing, no invented split.</p>' : ""}
        ${bridgeHtml}
        <div class="grid g4" style="margin-top:10px">
          ${caseCell("Bear", cases.bear)}
          ${caseCell("Market-implied", cases.market_implied)}
          ${caseCell("Base", cases.base)}
          ${caseCell("Bull", cases.bull)}
        </div>
      </section>

      <section id="chain">
        <h2>Demand → deployment causal chain</h2>
        <p>Weakest layer = <b>${miss(chain.weakest_link)}</b></p>
        <p class="muted">Keyword hits on customer filings are not a named contract with ${esc(data.ticker)}. ${esc(chain.note || "")}</p>
        <div class="chain">${chainHtml}</div>
      </section>

      <section id="implied">
        <h2>Market-implied growth under different multiple assumptions</h2>
        <p>Spot ${implied.spot != null ? esc(Number(implied.spot).toFixed(2)) : miss(implied.spot)} · Market-implied range <b>${miss(implied.market_implied_range_display)}</b> · vs PM Base <b>${miss(implied.vs_pm_base)}</b> · vs PM Bull <b>${miss(implied.vs_pm_bull)}</b></p>
        <p>${miss(implied.pm_wording)}</p>
        <div class="grid g2">
          <table class="matrix"><thead><tr><th>Multiple</th><th>Implied forward EPS</th><th>Implied 2y EPS CAGR</th></tr></thead><tbody>${sens}</tbody></table>
          <div class="cell">
            <p>PM Base growth: <b>${pct(implied.pm_base_growth)}</b></p>
            <p>PM Bull growth: <b>${pct(implied.pm_bull_growth)}</b></p>
            <p class="muted">The 33x row is market_implied_under_base_multiple, not the unique market growth rate.</p>
          </div>
        </div>
      </section>

      <section id="reaction">
        <h2>Why did ${esc(data.ticker)} fall despite positive fundamentals?</h2>
        <p class="muted">${miss(reaction.summary)}${reaction.applicable === false ? " (not a clean strong-print / down-tape case)" : ""}</p>
        <div class="grid g3">
          ${group("Confirmed", reaction.confirmed)}
          ${group("Plausible but unconfirmed", reaction.plausible_unconfirmed)}
          ${group("Unresolved", reaction.unresolved)}
        </div>
      </section>

      <section id="valuation">
        <h2>Valuation</h2>
        <p>Status ${pill(valuation.status, valuation.status)} ${
          (valuation.why_provisional || []).length
            ? "because " + esc((valuation.why_provisional || []).join("; "))
            : ""
        }</p>
        <table class="valtable">
          <thead><tr><th></th><th>Bear</th><th>Market-implied</th><th>Base</th><th>Bull</th></tr></thead>
          <tbody>
            ${valRow("Growth", "growth_display")}
            ${valRow("Margin", "margin")}
            ${valRow("EPS", "eps")}
            ${valRow("Multiple", "multiple")}
            ${valRow("Target", "target")}
            ${valRow("Origin", "origin")}
            ${valRow("Confidence", "confidence")}
          </tbody>
        </table>
      </section>

      <section id="monitor">
        <h2>Monitoring</h2>
        <div class="grid g2">${monitors}</div>
      </section>

      <section id="history">
        <h2>Thesis version history</h2>
        ${versions}
      </section>

      <section>
        <h2>Still missing / unresolved</h2>
        <p>${missing}</p>
      </section>
    `;
  }

  function boot() {
    const ticker = tickerFromPath();
    const nav = document.getElementById("ticker-nav");
    nav.innerHTML = DEFAULTS.map((item) =>
      `<a href="/research/${item}" class="${item === ticker ? "on" : ""}">${item}</a>`
    ).join("");
    document.title = `Research Review · ${ticker}`;
    fetch(`/api/research/${encodeURIComponent(ticker)}/review`)
      .then((res) => {
        if (!res.ok) throw new Error(`review ${res.status}`);
        return res.json();
      })
      .then((data) => {
        document.getElementById("rr-status").textContent = `${data.ticker || ticker} · ${(data.hero || {}).valuation_status || "loaded"}`;
        render(data);
      })
      .catch((err) => {
        document.getElementById("rr-status").textContent = "error";
        document.getElementById("root").innerHTML = `<p class="missing">Research review unavailable. ${esc(err.message || "")}</p>`;
      });
  }

  boot();
})();
