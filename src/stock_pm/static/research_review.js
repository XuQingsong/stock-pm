(() => {
  "use strict";

  const DEFAULTS = ["AVGO", "COHR", "XOM"];

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));

  const miss = (value) => {
    if (value === null || value === undefined || value === "" || value === "Missing") {
      return '<span class="muted">尚未解决</span>';
    }
    return esc(value);
  };

  const money = (value) => {
    if (value === null || value === undefined || value === "") return "待补";
    const n = Number(value);
    if (Number.isNaN(n)) return String(value);
    if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
    if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
    return String(n);
  };

  const pill = (label, kind) => `<span class="pill ${esc(kind || "")}">${esc(label || "待验证")}</span>`;

  const tickerFromPath = () => {
    const parts = location.pathname.split("/").filter(Boolean);
    return (parts[1] || "AVGO").toUpperCase();
  };

    const sourceLink = (row) => {
    if (row && row.source_url) {
      return `<a href="${esc(row.source_url)}" target="_blank" rel="noreferrer">${esc(row.source_zh || row.source || "来源")}</a>`;
    }
    if (row && (row.source_zh || row.source)) return esc(row.source_zh || row.source);
    return '<span class="unverified">来源未追溯</span>';
  };

  const evidenceBlock = (rows, label) => {
    const list = rows || [];
    if (!list.length) return `<p class="missing">${esc(label || "证据")}：尚未解决</p>`;
    return `<details class="ev"><summary>${esc(label || "查看证据")}（${list.length}）</summary>${
      list.map((row) => {
        const url = row.source_url
          ? `<a href="${esc(row.source_url)}" target="_blank" rel="noreferrer">来源</a>`
          : '<span class="unverified">来源未追溯</span>';
        return `<p>${esc(row.fact || "尚未解决")}<br><span class="muted">${esc(row.source || "")} · ${esc(row.source_time || "")} · ${url}</span>${
          row.excerpt && row.excerpt !== row.fact ? `<br>${esc(row.excerpt)}` : ""
        }</p>`;
      }).join("")
    }</details>`;
  };

  function render(data) {
    const ui = data.ui || {};
    const hero = data.hero || {};
    const tree = data.assumption_tree || {};
    const delivery = data.delivery_history || {};
    const customer = data.customer_side || {};
    const bridge = data.revenue_bridge || {};
    const implied = data.market_implied || {};
    const reaction = data.market_reaction || {};
    const valuation = data.valuation || {};
    const cases = ui.cases || {};
    const cust = ui.customer || {};
    const ledgerSum = ui.ledger_summary || {};
    const deliv = ui.delivery_summary || {};

    const caseCol = (key) => {
      const row = cases[key] || {};
      return `<div class="case"><div class="name">${esc(row.label || "")}</div><b>${esc(row.target || "待补")}</b>
        <div class="meta">EPS ${esc(row.eps)} · ${esc(row.growth)}${row.multiple === "待补" || row.multiple == null ? "" : ` · ${esc(row.multiple)}x`}</div></div>`;
    };

    const keyHtml = (ui.key_assumptions || []).map((row) => `<details>
      <summary>
        <div class="assump-title">${esc(row.title)}<div>${pill(row.status_label, row.status)}</div></div>
        <div>${esc(row.support)}<div class="muted">${esc(row.risk)}</div></div>
      </summary>
      <p class="muted">${esc(row.statement || "")}</p>
      ${evidenceBlock((row.node && row.node.supporting) || [], "支持证据")}
      ${evidenceBlock((row.node && row.node.opposing) || [], "反证")}
    </details>`).join("") || '<p class="missing">关键假设尚未形成</p>';

    const chainHtml = (ui.chain || []).map((layer, idx) => `${idx ? '<span class="muted">→</span>' : ""}
      <button type="button" class="chain-node ${layer.weakest ? "weak" : ""}" data-layer="${esc(layer.layer || "")}">
        <span class="nm">${esc(layer.label)}</span>
        <span class="st">${esc(layer.strength)}</span>
      </button>`).join("");

    const chainPanels = (ui.chain || []).map((layer) => `<div class="chain-panel" hidden data-panel="${esc(layer.layer || "")}">
      <b>${esc(layer.label)}</b> · ${esc(layer.strength)} · ${esc(layer.family || "")}
      ${layer.weakest ? " · 当前最薄弱环节" : ""}
      <p>${(layer.unresolved || []).map(esc).join("；") || "这一层暂无额外待验证说明"}</p>
      ${evidenceBlock(layer.evidence, "查看证据")}
    </div>`).join("");

    const monitorRows = (ui.monitor || []).map((row) => `<tr>
      <td>${esc(row.item)}</td>
      <td>${esc(row.current_state)}</td>
      <td>${esc(row.next_check)}</td>
      <td class="muted">${esc(row.swing)}</td>
    </tr>`).join("") || '<tr><td colspan="4" class="muted">跟踪项尚未建立</td></tr>';

    const treeHtml = (tree.branches || []).map((branch) => {
      const nodes = (branch.nodes || []).map((node) => `<details class="node">
        <summary><b>${esc(node.statement || "尚未解决")}</b> ${pill(node.status_label || node.status, node.status)} ${pill(node.role_label || node.thesis_role, node.thesis_role)}
          <span class="muted">支持 ${node.supporting_count ?? 0} · 反证 ${node.opposing_count ?? 0} · 待验证 ${node.unresolved_count ?? 0}</span>
        </summary>
        ${evidenceBlock(node.supporting, "支持证据")}
        ${evidenceBlock(node.opposing, "反证")}
        <p class="muted">下次验证：${miss(node.next_verification)}</p>
        <p class="muted">失效条件：${miss(node.invalidation)}</p>
        ${(node.unresolved_zh || node.unresolved || []).length ? `<p class="muted">${esc((node.unresolved_zh || node.unresolved).join("；"))}</p>` : ""}
      </details>`).join("") || '<p class="missing">这一支没有假设</p>';
      return `<div><h3>${esc(branch.title_zh || branch.title)}</h3>${nodes}</div>`;
    }).join("");

    const ledgerRows = (data.commitment_ledger || []).map((row) => `<tr>
      <td>${esc(row.commitment || "尚未解决")}${row.trace === "UNVERIFIED" ? ' <span class="unverified">来源未追溯</span>' : ""}</td>
      <td>${miss(row.date)}</td>
      <td>${sourceLink(row)}</td>
      <td>${miss(row.time_horizon_zh || row.time_horizon)}</td>
      <td>${miss(row.metric_zh || row.metric)}</td>
      <td>${miss(row.stated_value_or_range)}</td>
      <td>${pill(row.status_zh || "待验证", row.status)}</td>
      <td>${miss(row.next_check_zh || row.next_check)}</td>
    </tr>`).join("") || '<tr><td colspan="8" class="muted">尚未建立承诺记录</td></tr>';

    const hist = (delivery.history || []).map((row) => {
      const g = row.guidance || {};
      const a = row.actual || {};
      const outcome = row.outcome === "missed" ? "miss" : (row.outcome || "unscored");
      const outcomeZh = { beat: "超预期", met: "符合预期", miss: "低于预期", unscored: "未评分" }[outcome] || outcome;
      return `<tr>
        <td>${esc(row.quarter || row.period || "待补")}</td>
        <td>${esc(g.kind === "insufficient_data" ? "数据不足" : (g.kind || "数据不足"))}${g.eps_estimate != null ? ` · EPS ${esc(g.eps_estimate)}` : ""}</td>
        <td>${a.eps != null ? `EPS ${esc(a.eps)}` : "待补"}</td>
        <td>${pill(outcomeZh, outcome)}</td>
        <td>${row.guidance_revision && row.guidance_revision !== "unchanged" ? "有修订" : "—"}</td>
        <td>${miss(row.source)}</td>
      </tr>`;
    }).join("") || '<tr><td colspan="6" class="muted">兑现记录尚未建立</td></tr>';

    const versions = (data.thesis_history || []).map((row) => `<details class="node">
      <summary>第 ${esc(row.version)} 版 · ${esc(row.what_changed === "initial thesis" ? "初始逻辑" : (row.what_changed === "thesis version incremented" ? "逻辑版本更新" : row.what_changed || ""))}</summary>
      <p>${esc(row.core_thesis || "")}</p>
    </details>`).join("") || '<p class="missing">尚无版本历史</p>';

    const mark = (ok, yes, no) => `<span class="${ok ? "yes" : "no"}">${ok ? yes : no}</span>`;

    document.getElementById("root").innerHTML = `
      <section id="conclusion">
        <div class="ident">
          <div>${esc(data.ticker)} <b>${esc(data.legal_name || data.ticker)}</b></div>
          <div>当前股价 <b>${hero.spot != null ? esc(Number(hero.spot).toFixed(2)) : "待补"}</b></div>
          <div>逻辑可信度 <b>${miss(ui.confidence_band)}${ui.confidence_value != null ? ` · ${esc(ui.confidence_value)}` : ""}</b></div>
          <div>估值可靠性 <b>${esc(ui.valuation_reliability || "待补")}</b>${ui.valuation_why ? `<div class="muted">${esc(ui.valuation_why)}</div>` : ""}</div>
        </div>
        <h1>${esc(ui.headline || "投资逻辑仍待补全")}</h1>
        <div class="cards3">
          <div class="card"><h3>为什么值得关注</h3><p>${esc(ui.why_watch || "待补")}</p></div>
          <div class="card"><h3>最大风险</h3><p>${esc(ui.biggest_risk || "待补")}</p></div>
          <div class="card"><h3>下一步验证</h3><p>${esc(ui.next_check || "下次官方更新")}</p></div>
        </div>
        <details class="deep" id="full-thesis"><summary>完整研究逻辑</summary>
          <p>${esc(hero.core_thesis || "")}</p>
          ${hero.core_thesis_full && hero.core_thesis_full !== hero.core_thesis ? `<p class="muted">${esc(hero.core_thesis_full)}</p>` : ""}
          <p class="muted">短期：${esc(hero.short_term_view || "")}</p>
          <p class="muted">中期：${esc(hero.mid_term_view || "")}</p>
          <p class="muted">长期：${esc(hero.long_term_view || "")}</p>
        </details>
      </section>

      <section id="judgment">
        <h2>投资判断</h2>
        <div class="cases">
          ${caseCol("bear")}${caseCol("market_implied")}${caseCol("base")}${caseCol("bull")}
        </div>
        <p class="note">${esc(ui.judgment_note || "")}</p>
        <p class="muted">目标价 / EPS / 增长 / 估值倍数。增长在市场隐含一列是不同估值倍数下的反推区间，不是单一增长率。</p>
      </section>

      <section id="assumptions">
        <h2>三个关键假设</h2>
        <div class="assumptions">${keyHtml}</div>
        <p><button class="text-btn" type="button" data-open="tree-detail">查看全部假设</button></p>
      </section>

      <section id="chain">
        <h2>需求兑现链条</h2>
        <p class="muted">最弱环节：${esc(ui.weakest_layer || "尚未判断")}。点击节点查看证据。</p>
        <div class="chain-row">${chainHtml}</div>
        ${chainPanels}
      </section>

      <section id="monitor">
        <h2>下一步重点跟踪</h2>
        <table class="monitor">
          <thead><tr><th>观察项</th><th>当前状态</th><th>下次验证</th><th>增强 / 削弱</th></tr></thead>
          <tbody>${monitorRows}</tbody>
        </table>
      </section>

      <section id="customer-brief">
        <h2>客户侧独立验证</h2>
        <div class="checks">
          <div class="check"><span>行业需求</span>${mark(cust.industry, "已确认", "尚未确认")}</div>
          <div class="check"><span>独立客户公开文件支持该公司具体合同</span>${mark(cust.named, "已确认", "尚未确认")}</div>
          <div class="check"><span>直接客户点名该公司</span>${mark(cust.direct, "已发现", "尚未发现")}</div>
        </div>
        <p>${esc(cust.summary || "")}</p>
      </section>

      <section>
        <h2>管理层承诺与兑现</h2>
        <div class="summary-strip">
          <span>承诺 <b>${esc(ledgerSum.total ?? 0)}</b> 条</span>
          <span>已兑现 <b>${esc(ledgerSum.delivered ?? 0)}</b></span>
          <span>待验证 <b>${esc(ledgerSum.pending ?? 0)}</b></span>
          <span>延迟 <b>${esc(ledgerSum.delayed ?? 0)}</b></span>
          <span>失效 <b>${esc(ledgerSum.broken ?? 0)}</b></span>
        </div>
        <p class="muted">下一次重要验证：${esc(ledgerSum.next || "下次财报对照承诺")}</p>
        <p>最近可评分季度：<b>${esc(deliv.beat ?? 0)} 次超预期 / ${esc(deliv.missed ?? 0)} 次低于预期</b>（另有符合预期 ${esc(deliv.met ?? 0)}）</p>
        <p class="muted">${esc(deliv.note || "")}</p>
      </section>

      <details class="deep" id="deep">
        <summary>查看详细研究</summary>
        <details class="block" id="tree-detail"><summary>查看全部假设</summary>${treeHtml || '<p class="missing">假设树尚未建立</p>'}</details>
        <details class="block" id="ledger-detail"><summary>查看全部承诺</summary>
          <table class="plain"><thead><tr><th>承诺</th><th>日期</th><th>来源</th><th>期限</th><th>指标</th><th>数值</th><th>状态</th><th>下次验证</th></tr></thead><tbody>${ledgerRows}</tbody></table>
        </details>
        <details class="block" id="delivery-detail"><summary>查看兑现记录</summary>
          <p class="muted">已评分：${esc((delivery.scored_quarters || []).join("、") || "无")} · 未评分：${esc((delivery.unscored_quarters || []).join("、") || "无")}</p>
          <table class="plain"><thead><tr><th>季度</th><th>指引</th><th>实际</th><th>结果</th><th>修订</th><th>来源</th></tr></thead><tbody>${hist}</tbody></table>
        </details>
        <details class="block"><summary>查看客户侧证据</summary>
          ${evidenceBlock(customer.issuer_management, "公司管理层")}
          ${evidenceBlock(customer.independent_customer, "独立客户来源")}
          ${evidenceBlock(customer.industry_third_party, "行业第三方")}
          ${evidenceBlock(customer.industry_demand_only, "仅支持行业需求")}
        </details>
        <details class="block"><summary>查看收入增长来源</summary>
          <p>${bridge.mode === "top_down_range" || bridge.origin === "estimated" ? "自上而下区间 / 估算 — 缺少官方分部结构，不补假拆分。" : ""}</p>
          <p>当前收入 ${money(bridge.current_revenue)}</p>
          ${(bridge.lines || []).map((line) => `<p>${esc(line.label || "未知 / 缺失")} · ${line.latest_print_revenue != null ? money(line.latest_print_revenue) : "待补 / 估算"} · ${esc(line.origin === "estimated" ? "估算" : (line.origin || ""))}</p>`).join("")}
        </details>
        <details class="block"><summary>为什么基本面不错，股价却下跌？</summary>
          <p>${miss(reaction.summary)}${reaction.applicable === false ? "（这一窗口不是典型的好财报却下跌）" : ""}</p>
          <p><b>已确认</b></p>${(reaction.confirmed || []).map((row) => `<p>${esc(row.text || "")}${evidenceBlock(row.evidence, "查看证据")}</p>`).join("") || '<p class="missing">尚未确认</p>'}
          <p><b>可能但未证实</b></p>${(reaction.plausible_unconfirmed || []).map((row) => `<p>${esc(row.text || "")}${evidenceBlock(row.evidence, "查看证据")}</p>`).join("") || '<p class="missing">暂无</p>'}
          <p><b>尚未解决</b></p>${(reaction.unresolved || []).map((row) => `<p>${esc(row.text || "")}${evidenceBlock(row.evidence, "查看证据")}</p>`).join("") || '<p class="missing">暂无</p>'}
        </details>
        <details class="block"><summary>查看估值细节</summary>
          <p>估值可靠性：${esc(ui.valuation_reliability || "")} ${esc(ui.valuation_why || "")}</p>
          <p>${esc(implied.title || "当前股价隐含的增长预期")} · 区间 ${esc(implied.market_implied_range_display || "待补")}</p>
          <table class="plain"><thead><tr><th>估值倍数</th><th>隐含远期 EPS</th><th>隐含两年 EPS 复合增速</th></tr></thead>
          <tbody>${(implied.sensitivity || []).map((row) => `<tr><td>${esc(row.multiple)}${row.is_base_multiple ? "（基准）" : ""}</td><td>${miss(row.implied_forward_eps)}</td><td>${miss(row.implied_2y_eps_cagr_display)}</td></tr>`).join("") || '<tr><td colspan="3">待补</td></tr>'}</tbody></table>
          <p class="muted">基准一列的增长是在基准估值倍数下反推，不是市场唯一隐含增速。</p>
        </details>
        <details class="block"><summary>查看投资逻辑变化历史</summary>${versions}</details>
        <details class="block"><summary>尚未解决的问题</summary><p>${esc((ui.missing || []).join("；") || "未另列")}</p></details>
      </details>
    `;

    document.querySelectorAll("[data-open]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const el = document.getElementById(btn.getAttribute("data-open"));
        if (!el) return;
        const deep = document.getElementById("deep");
        if (deep) deep.open = true;
        el.open = true;
        el.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
    document.querySelectorAll(".chain-node").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-layer");
        document.querySelectorAll(".chain-panel").forEach((panel) => {
          panel.hidden = panel.getAttribute("data-panel") !== id;
        });
      });
    });
  }

  function boot() {
    const ticker = tickerFromPath();
    const nav = document.getElementById("ticker-nav");
    nav.innerHTML = DEFAULTS.map((item) =>
      `<a href="/research/${item}" class="${item === ticker ? "on" : ""}">${item}</a>`
    ).join("");
    document.title = `投资研究 · ${ticker}`;
    fetch(`/api/research/${encodeURIComponent(ticker)}/review`)
      .then((res) => {
        if (!res.ok) throw new Error(`无法读取研究结论 ${res.status}`);
        return res.json();
      })
      .then((data) => {
        document.getElementById("rr-status").textContent = `${data.ticker || ticker} · ${((data.ui || {}).valuation_reliability) || "已载入"}`;
        render(data);
      })
      .catch((err) => {
        document.getElementById("rr-status").textContent = "出错";
        document.getElementById("root").innerHTML = `<p class="missing">研究页暂时无法打开。${esc(err.message || "")}</p>`;
      });
  }

  boot();
})();
