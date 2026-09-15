(() => {
  "use strict";

  const DEFAULTS = ["AVGO", "COHR", "XOM"];

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));

  const miss = (value, fallback) => {
    if (value === null || value === undefined || value === "" || value === "Missing") {
      return `<span class="muted">${esc(fallback || "尚未由模型给出")}</span>`;
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

  const renderDesk = (data) => {
    const desk = data.pm_reasoning || {};
    const count = Number(desk.evidence_count || 0);
    const compressed = Boolean(desk.compressed);
    const vars = (desk.decisive_variables || []).slice(0, 3);
    const changing = (desk.top_thesis_changing_evidence || []).slice(0, 5);
    const gaps = (desk.market_disagreement || []).slice(0, 2);
    const countLine = compressed
      ? `<p class="compress on">从 <b>${esc(count || "全部")}</b> 条材料里，只留下会改变判断的 <b>${changing.length}</b> 条。<br>真正决定投资结果的，只有 <b>${vars.length}</b> 个变量。</p>`
      : '<p class="compress off">模型还没有完成压缩。下面仍是规则结论，不是把材料压成 5 条证据之后的判断。</p>';

    const varHtml = vars.length
      ? vars.map((row, idx) => `<article class="var">
          <div class="idx">${idx + 1}</div>
          <div>
            <h3>${esc(row.name)}</h3>
            <p>${miss(row.current_view)}</p>
            <p class="muted">${miss(row.why_decisive)}</p>
            ${row.next_check ? `<p class="next">下次核对：${esc(row.next_check)}</p>` : ""}
          </div>
        </article>`).join("")
      : '<p class="missing">尚未压出决定未来回报的三个变量。</p>';

    const gapHtml = gaps.length
      ? gaps.map((row) => `<article class="split">
          <div class="pair">
            <div><h3>我们认为</h3><p>${miss(row.pm_believes)}</p></div>
            <div><h3>市场在定价</h3><p>${miss(row.market_appears_to_price)}</p></div>
          </div>
          <p class="why">${miss(row.why_pm_differs)}</p>
        </article>`).join("")
      : '<p class="missing">尚未形成与市场可对照的真正分歧。</p>';

    const topHtml = changing.length
      ? `<ol class="top5">${changing.map((row) => `<li>
          <p class="fact">${miss(row.fact, "证据事实待补")}</p>
          <p class="muted">${miss(row.why, "尚未说明为何改变判断")}</p>
        </li>`).join("")}</ol>`
      : '<p class="missing">还没有从材料中压出改变判断的五条证据。</p>';

    const hypo = (desk.competing_hypotheses || []).slice(0, 4);
    const hypoHtml = hypo.length
      ? hypo.map((row) => `<article class="hypo">
          <p><b>${miss(row.probability_band, "待定")}</b> ${esc(row.statement || "")}</p>
          ${row.impact_if_true ? `<p class="muted">若成立：${esc(row.impact_if_true)}</p>` : ""}
        </article>`).join("")
      : '<p class="missing">尚未生成竞争假设。</p>';

    const cf = (desk.counterfactuals || []).slice(0, 4);
    const cfHtml = cf.length
      ? cf.map((row) => `<p><b>如果 ${esc(row.if || "")}</b> — ${miss(row.thesis_impact)} ${row.eps_or_valuation_direction ? `（${esc(row.eps_or_valuation_direction)}）` : ""}</p>`).join("")
      : '<p class="missing">尚未做反事实推理。</p>';

    const low = (desk.low_value_evidence || desk.non_thesis_changing_evidence || []).slice(0, 3);
    const lowHtml = low.length
      ? `<ul class="low">${low.map((row) => `<li><p>${miss(row.fact)}</p><p class="muted">不改变判断：${miss(row.why)}</p></li>`).join("")}</ul>`
      : '<p class="missing">没有单独标出看起来重要但不改变判断的材料。</p>';

    return `
      <section class="desk" id="desk">
        <div class="ident">
          <div>${esc(data.ticker)} <b>${esc(data.legal_name || data.ticker)}</b></div>
        </div>
        ${countLine}
        <section>
          <h2>当前结论</h2>
          <p class="lead">${miss(desk.conclusion, "投资结论尚未形成")}</p>
          ${desk.core_contradiction ? `<p class="contradiction">${esc(desk.core_contradiction)}</p>` : ""}
        </section>
        <section>
          <h2>三个决定性变量</h2>
          <div class="vars">${varHtml}</div>
        </section>
        <section>
          <h2>与市场真正分歧</h2>
          <div class="splits">${gapHtml}</div>
        </section>
        <section>
          <h2>最可能错在哪里</h2>
          <p>${miss(desk.most_likely_wrong)}</p>
        </section>
        <section>
          <h2>改变判断的五条证据</h2>
          ${topHtml}
        </section>
        <section>
          <h2>下一条最值得等待的新证据</h2>
          <p>${miss(desk.next_information_to_seek)}</p>
        </section>
      </section>
      <details class="deep" id="deep">
        <summary>详细研究</summary>
        <details class="block" open><summary>竞争假设</summary>${hypoHtml}</details>
        <details class="block"><summary>反事实</summary>${cfHtml}</details>
        <details class="block"><summary>看起来重要、但不改变判断</summary>${lowHtml}</details>
        ${desk.what_would_change_my_mind ? `<details class="block"><summary>什么会让判断改口</summary><p>${esc(desk.what_would_change_my_mind)}</p></details>` : ""}
    `;
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
    const cases = ui.cases || {};
    const cust = ui.customer || {};
    const ledgerSum = ui.ledger_summary || {};
    const deliv = ui.delivery_summary || {};

    const caseCol = (key) => {
      const row = cases[key] || {};
      return `<div class="case"><div class="name">${esc(row.label || "")}</div><b>${esc(row.target || "待补")}</b>
        <div class="meta">EPS ${esc(row.eps)} · ${esc(row.growth)}${row.multiple === "待补" || row.multiple == null ? "" : ` · ${esc(row.multiple)}x`}</div></div>`;
    };

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

    const treeHtml = (tree.branches || []).map((branch) => {
      const nodes = (branch.nodes || []).map((node) => `<details class="node">
        <summary><b>${esc(node.statement || "尚未解决")}</b> ${pill(node.status_label || node.status, node.status)} ${pill(node.role_label || node.thesis_role, node.thesis_role)}
          <span class="muted">支持 ${node.supporting_count ?? 0} · 反证 ${node.opposing_count ?? 0} · 待验证 ${node.unresolved_count ?? 0}</span>
        </summary>
        ${evidenceBlock(node.supporting, "支持证据")}
        ${evidenceBlock(node.opposing, "反证")}
        <p class="muted">下次验证：${miss(node.next_verification)}</p>
        <p class="muted">失效条件：${miss(node.invalidation)}</p>
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

    document.getElementById("root").innerHTML = `${renderDesk(data)}
        <details class="block"><summary>估值情景</summary>
          <div class="cases">${caseCol("bear")}${caseCol("market_implied")}${caseCol("base")}${caseCol("bull")}</div>
          <p class="muted">${esc(ui.judgment_note || "")}</p>
        </details>
        <details class="block"><summary>需求兑现链条</summary>
          <p class="muted">最弱环节：${esc(ui.weakest_layer || "尚未判断")}</p>
          <div class="chain-row">${chainHtml}</div>
          ${chainPanels}
        </details>
        <details class="block"><summary>客户侧独立验证</summary>
          <div class="checks">
            <div class="check"><span>行业需求</span>${mark(cust.industry, "已确认", "尚未确认")}</div>
            <div class="check"><span>独立客户公开文件支持该公司具体合同</span>${mark(cust.named, "已确认", "尚未确认")}</div>
            <div class="check"><span>直接客户点名该公司</span>${mark(cust.direct, "已发现", "尚未发现")}</div>
          </div>
          <p>${esc(cust.summary || "")}</p>
          ${evidenceBlock(customer.issuer_management, "公司管理层")}
          ${evidenceBlock(customer.independent_customer, "独立客户来源")}
          ${evidenceBlock(customer.industry_third_party, "行业第三方")}
        </details>
        <details class="block"><summary>假设树</summary>${treeHtml || '<p class="missing">假设树尚未建立</p>'}</details>
        <details class="block"><summary>承诺与兑现</summary>
          <div class="summary-strip">
            <span>承诺 <b>${esc(ledgerSum.total ?? 0)}</b> 条</span>
            <span>已兑现 <b>${esc(ledgerSum.delivered ?? 0)}</b></span>
            <span>待验证 <b>${esc(ledgerSum.pending ?? 0)}</b></span>
          </div>
          <p class="muted">${esc(deliv.note || "")}</p>
          <table class="plain"><thead><tr><th>承诺</th><th>日期</th><th>来源</th><th>期限</th><th>指标</th><th>数值</th><th>状态</th><th>下次验证</th></tr></thead><tbody>${ledgerRows}</tbody></table>
          <table class="plain"><thead><tr><th>季度</th><th>指引</th><th>实际</th><th>结果</th><th>修订</th><th>来源</th></tr></thead><tbody>${hist}</tbody></table>
        </details>
        <details class="block"><summary>收入增长来源</summary>
          <p>当前收入 ${money(bridge.current_revenue)}</p>
          ${(bridge.lines || []).map((line) => `<p>${esc(line.label || "未知 / 缺失")} · ${line.latest_print_revenue != null ? money(line.latest_print_revenue) : "待补 / 估算"}</p>`).join("")}
        </details>
        <details class="block"><summary>价格反应</summary>
          <p>${miss(reaction.summary)}</p>
        </details>
        <details class="block"><summary>估值细节</summary>
          <p>${esc(implied.title || "")} · 区间 ${esc(implied.market_implied_range_display || "待补")}</p>
        </details>
        <details class="block"><summary>投资逻辑变化历史</summary>${versions}</details>
        <details class="block"><summary>尚未解决的问题</summary><p>${esc((ui.missing || []).join("；") || "未另列")}</p></details>
        <details class="block"><summary>完整研究逻辑原文</summary>
          <p>${esc(hero.core_thesis || "")}</p>
        </details>
      </details>
    `;

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
        const desk = data.pm_reasoning || {};
        document.getElementById("rr-status").textContent = desk.compressed
          ? `${data.ticker || ticker} · 已压缩为 3 个变量 / 5 条证据`
          : `${data.ticker || ticker} · 规则结论`;
        render(data);
      })
      .catch((err) => {
        document.getElementById("rr-status").textContent = "出错";
        document.getElementById("root").innerHTML = `<p class="missing">研究页暂时无法打开。${esc(err.message || "")}</p>`;
      });
  }

  boot();
})();
