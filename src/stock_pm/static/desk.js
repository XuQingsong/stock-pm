(() => {
  "use strict";

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);

  const api = async (path) => {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `${path} ${response.status}`);
    return body;
  };

  function barsHtml(count) {
    const n = Number(count) || 0;
    return `<span class="bars" aria-hidden="true">${[0, 1, 2].map((i) => `<i class="${i < n ? "on" : ""}"></i>`).join("")}</span>`;
  }

  function newsLink(news) {
    if (news && news.url) {
      return `<a class="news-link" href="${esc(news.url)}" target="_blank" rel="noopener noreferrer">${esc(news.label || "可点新闻")}</a>`;
    }
    return `<span class="no-url muted" style="font-size:0.78rem">无原文链接</span>`;
  }

  function basisHtml(basis) {
    const row = basis || {};
    return `<details class="expand-b">
      <summary>展开依据 · 事实→变化→预期→为何此强度→消失条件</summary>
      <div class="expand-chain">
        <div class="expand-step"><span class="step-label">事实</span>${esc(row.fact || "事实暂缺")}</div>
        <div class="expand-step"><span class="step-label">变化</span>${esc(row.change || "变化暂缺")}</div>
        <div class="expand-step"><span class="step-label">预期</span>${esc(row.expectation || "预期暂缺")}</div>
        <div class="expand-step"><span class="step-label">为何此强度</span>${esc(row.why_strength || "强度依据暂缺")}</div>
        <div class="expand-step"><span class="step-label">影响消失条件</span>${esc(row.invalidation || "失效条件暂缺")}</div>
      </div>
    </details>`;
  }

  function eventCard(card, featured) {
    if (!card) return "";
    const kind = card.impact_class || "gray";
    const tickers = (card.tickers || []).map((row) =>
      `<span class="ticker-impact ${esc(row.impact_class || "gray")}">${esc(row.symbol)} ${barsHtml(row.bars)} ${esc(row.label || "")}</span>`
    ).join("");
    const compact = featured ? "" : " compact";
    return `<article class="card event-card${featured ? " event-featured" : compact} ${esc(kind)}">
      <div class="event-head">
        ${featured ? '<span class="featured-badge">首条</span>' : ""}
        <span class="impact-pill ${esc(kind)}">${esc(card.impact_label || "")}</span>
        <span class="chip">${esc(card.scope_label || "")}</span>
      </div>
      <h3 class="event-title">${esc(card.title || "")}</h3>
      <p class="event-conclusion">${featured ? "结论：" : ""}${esc(card.conclusion || "")}</p>
      ${featured ? `<div class="event-meta"><span>期限：<strong>${esc(card.horizon || "期限暂缺")}</strong></span></div>` : ""}
      ${tickers ? `<div class="impact-row">${featured ? '<span class="label">影响谁</span>' : ""}${tickers}</div>` : ""}
      ${card.transmit ? `<p class="transmit">传导：${esc(card.transmit)}</p>` : ""}
      ${basisHtml(card.basis)}
      ${newsLink(card.news)}
    </article>`;
  }

  function focusRow(row) {
    return `<a class="focus-row urgency-${esc(row.urgency || "mute")}" href="${esc(row.href || "#")}" role="listitem">
      <span class="focus-urgency" aria-hidden="true"></span>
      <div class="focus-main">
        <div class="focus-line1">
          <span class="focus-ticker">${esc(row.symbol)}</span><span class="focus-sep">｜</span><span class="focus-state">${esc(row.state || "")}</span>
        </div>
        <p class="focus-why">${esc(row.why || "")}</p>
        <p class="focus-hint">${esc(row.hint || "")}</p>
      </div>
      <span class="focus-chevron" aria-hidden="true">›</span>
    </a>`;
  }

  function bindCarousel(root) {
    const track = root.querySelector("#car-track");
    const cards = track ? track.querySelectorAll(".event-card") : [];
    let idx = 0;
    let timer = null;
    const btnPause = root.querySelector("#btn-pause");
    const counter = root.querySelector("#car-idx");
    const dots = root.querySelector("#car-dots");
    function scrollTo(i) {
      if (!cards.length) return;
      idx = (i + cards.length) % cards.length;
      cards[idx].scrollIntoView({ behavior: "smooth", inline: "start", block: "nearest" });
      if (counter) counter.textContent = String(idx + 1);
      if (dots) {
        dots.querySelectorAll("button").forEach((btn, n) => btn.classList.toggle("on", n === idx));
      }
    }
    if (dots && cards.length) {
      dots.innerHTML = "";
      cards.forEach((_, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.setAttribute("aria-label", `第${i + 1}条`);
        if (i === 0) b.className = "on";
        b.addEventListener("click", () => scrollTo(i));
        dots.appendChild(b);
      });
    }
    function play() {
      if (btnPause) {
        btnPause.textContent = "暂停";
        btnPause.classList.add("active-pause");
        btnPause.setAttribute("aria-pressed", "false");
      }
      clearInterval(timer);
      timer = setInterval(() => scrollTo(idx + 1), 6000);
    }
    function pause() {
      if (btnPause) {
        btnPause.textContent = "播放";
        btnPause.classList.remove("active-pause");
        btnPause.setAttribute("aria-pressed", "true");
      }
      clearInterval(timer);
    }
    const bp = root.querySelector("#btn-prev");
    const bn = root.querySelector("#btn-next");
    if (bp) bp.addEventListener("click", () => scrollTo(idx - 1));
    if (bn) bn.addEventListener("click", () => scrollTo(idx + 1));
    if (btnPause) btnPause.addEventListener("click", () => {
      if (btnPause.getAttribute("aria-pressed") === "true") play();
      else pause();
    });
    pause();
  }

  function renderOverview(data) {
    const featured = data.featured
      ? eventCard(data.featured, true)
      : `<p class="empty-note">${esc(data.featured_missing || "今日没有可置顶的主事件。")}</p>`;
    const focus = data.focus || {};
    const priority = (focus.priority || []).map(focusRow).join("");
    const watch = (focus.watch || []).map(focusRow).join("");
    const skip = (focus.skip || []).map(focusRow).join("");
    const carousel = data.carousel || [];
    const unmapped = data.unmapped || [];
    const first = (data.watchlist || [])[0];
    const stockHref = first ? `/stock/${encodeURIComponent(first.symbol)}` : "/settings";
    return {
      stockHref,
      html: `
      <section class="section" aria-labelledby="sec-events">
        <h2 class="section-label" id="sec-events">市场主事件</h2>
        ${featured}
      </section>
      <section class="section focus-today" aria-labelledby="sec-focus">
        <h2 class="section-label" id="sec-focus">今日重点关注
          <span class="muted" style="font-weight:500;font-size:0.75rem">因新闻需留意的自选 · 整行进个股</span>
        </h2>
        <p class="focus-lead">${esc(focus.lead || "")}</p>
        ${focus.empty ? `<p class="empty-note">${esc(focus.empty)}</p>` : ""}
        ${(focus.priority || []).length ? `<div class="focus-group"><h3 class="focus-group-title">今天建议优先看</h3><div class="focus-list" role="list">${priority}</div></div>` : ""}
        ${(focus.watch || []).length ? `<div class="focus-group"><h3 class="focus-group-title">留意条件</h3><div class="focus-list" role="list">${watch}</div></div>` : ""}
        <details class="focus-muted-fold">
          <summary>今天可先不点开：${Number(focus.skip_count || 0)}只</summary>
          <div class="focus-list" role="list">${skip || '<p class="empty-note">没有可先不点开的标的。</p>'}</div>
        </details>
      </section>
      <section class="section" aria-labelledby="sec-carousel">
        <h2 class="section-label" id="sec-carousel">其余市场事件
          <span class="muted" style="font-weight:500;font-size:0.75rem">横滑 / 可暂停 · 不挡「今日重点关注」</span>
        </h2>
        ${carousel.length ? `<div class="carousel-wrap" id="event-carousel">
          <div class="carousel-toolbar">
            <span class="hint">其余事件 · 横向切换 / 自动轮播</span>
            <div class="carousel-controls">
              <button type="button" id="btn-prev" aria-label="上一条">‹</button>
              <button type="button" id="btn-pause" class="active-pause" aria-pressed="false">暂停</button>
              <button type="button" id="btn-next" aria-label="下一条">›</button>
              <span class="counter"><span id="car-idx">1</span>/${carousel.length}</span>
            </div>
          </div>
          <div class="carousel-track" id="car-track">${carousel.map((card) => eventCard(card, false)).join("")}</div>
          <div class="carousel-dots" id="car-dots" aria-hidden="true"></div>
        </div>` : `<p class="empty-note">没有其余可展示事件。</p>`}
        <details class="fold-c">
          <summary>无法映射标的的其他头条（折叠）</summary>
          <div class="fold-body">${unmapped.length ? unmapped.map((row) => `<div>${esc(row.title || "")} · ${esc(row.note || "")}</div>`).join("") : "没有未映射头条。"}</div>
        </details>
      </section>`
    };
  }

  function renderStock(data) {
    const judge = data.judge || {};
    const change = data.thesis_change || {};
    const mid = change.midterm || {};
    const verbs = (judge.actions || []).map((v) => `<span class="action-verb">${esc(v)}</span>`).join("");
    const todayVerbs = ((change.today_action || {}).verbs || []).map((v) => `<span class="action-verb">${esc(v)}</span>`).join("");
    const drivers = (data.drivers || []).map((row) => `<li>
      <span class="driver-rank">${esc(row.rank)}</span>
      <div class="driver-body">
        <span class="impact-pill ${esc(row.impact_class || "gray")}">${esc(row.impact_label || "")}</span>
        <strong style="margin-left:6px">${esc(row.title || "")}</strong>
        <span class="why">因：${esc(row.why || "")}</span>
      </div>
    </li>`).join("") || "<li>驱动因素暂缺</li>";
    const risks = (data.risks || []).map((item) => `<li>${esc(item)}</li>`).join("");
    return `
      <section class="section">
        <div class="card judge-block ${esc(judge.impact_class || "gray")}">
          <h2 class="block-title"><span class="block-num">1</span>当前判断</h2>
          <p class="judge-stance">${esc(judge.stance || "判断暂缺")}</p>
          <p class="judge-quote">「${esc(judge.quote || "")}」</p>
          <p class="action-line" style="margin:10px 0 0">${verbs}</p>
        </div>
      </section>
      <section class="section">
        <div class="card thesis-change">
          <h2 class="block-title"><span class="block-num">2</span>与昨天相比发生了什么</h2>
          <div class="thesis-fromto" aria-label="判断变化">
            <div class="thesis-side"><span class="thesis-label">昨</span><strong>${esc(change.yesterday || "昨：数据暂缺")}</strong></div>
            <span class="thesis-arrow" aria-hidden="true">→</span>
            <div class="thesis-side now"><span class="thesis-label">今</span><strong>${esc(change.today || "今：判断暂缺")}</strong></div>
          </div>
          <p class="thesis-delta-tag">${change.changed ? '<span class="chip chip-ok">判断变了</span> ' : '<span class="chip">判断未变</span> '}${esc(change.delta || "")}</p>
          <div class="delta-sentence">
            <span class="part"><span class="k">原因</span>${esc(change.reason || "")}</span>
            <span class="part"><span class="k">中期逻辑</span><strong class="mid-unchanged">${mid.unchanged === false ? "有变" : "不变"}</strong> ${esc(mid.text || "")}</span>
            <span class="part"><span class="k">今日动作</span>${todayVerbs}
              <span class="muted" style="font-size:0.75rem">${esc((change.today_action || {}).hint || "")}</span>
            </span>
          </div>
        </div>
      </section>
      <section class="section">
        <div class="card">
          <h2 class="block-title"><span class="block-num">3</span>影响最大的三个驱动因素</h2>
          <ol class="driver-list">${drivers}</ol>
        </div>
      </section>
      <section class="section">
        <div class="card">
          <h2 class="block-title"><span class="block-num">4</span>风险和反证</h2>
          <ul class="risk-list">${risks}</ul>
        </div>
      </section>
      <section class="section">
        <div class="card">
          <h2 class="block-title"><span class="block-num">5</span>观察条件与失效条件</h2>
          <div class="cond-grid">
            <div class="cond-box observe"><h4>观察</h4>${esc(data.observe || "观察条件暂缺")}</div>
            <div class="cond-box invalidate"><h4>失效（到这条就作废原判断）</h4>${esc(data.invalidate || "失效条件暂缺")}</div>
          </div>
        </div>
      </section>`;
  }

  function renderReview(data) {
    const formal = (data.formal || []).map((card) => `<article class="pred-formal">
      <div><span class="badge-formal">正式预测</span><span class="pred-id">${esc(card.as_of_label || "")}</span></div>
      <div class="pred-ticker">${esc(card.symbol || "")}</div>
      <div class="pred-section">
        <h4>当时正式预测了什么</h4>
        <div class="pred-fields">
          <span>方向：<strong>${esc(card.direction)}</strong></span>
          <span>窗：<strong>${esc(card.window)}</strong></span>
          <span>上界 <strong>${esc(card.upside)}</strong> / 下界 <strong>${esc(card.downside)}</strong></span>
        </div>
        <div class="pred-fields">
          <span>基准：<strong>${esc(card.baseline)}</strong></span>
          <span>失效：<strong>${esc(card.invalidation)}</strong></span>
        </div>
        <div class="pred-fields">
          <span>数据时间：<strong>${esc(card.data_time)}</strong></span>
          <span>证据版本：<strong>${esc(card.evidence_version)}</strong></span>
        </div>
      </div>
      <div class="pred-section"><h4>实际发生了什么</h4><p>${esc(card.actual)}</p></div>
      <div class="pred-section"><h4>哪条证据有效 / 被高估</h4><ul>${(card.evidence_lines || []).map((line) => `<li>${esc(line)}</li>`).join("")}</ul></div>
      <div class="pred-section"><h4>预测后新信息</h4><p>${esc(card.new_info)}</p></div>
      <div class="pred-section"><h4>当前判断如何修正</h4><p>${esc(card.revision)}</p></div>
    </article>`).join("") || `<p class="empty-note">${esc(data.empty_formal || "本周没有字段齐全、可进校验的正式预测。")}</p>`;
    const learning = (data.learning || []).map((card) => `<article class="card learn-card">
      <h3>${esc(card.symbol)} · 学到什么</h3>
      <ul class="learn-list">
        <li><span class="k">对在哪</span>${esc(card.right)}</li>
        <li><span class="k">错在哪</span>${esc(card.wrong)}</li>
        <li><span class="k">下次</span>${esc(card.next)}</li>
      </ul>
    </article>`).join("");
    const observations = (data.observations || []).map((card) => `<article class="pred-observe">
      <div><span class="badge-observe">观察</span></div>
      <div class="pred-ticker">${esc(card.title || card.symbol)}</div>
      <p>${esc(card.text)}</p>
      <div class="warn-incomplete">${esc(card.note)}</div>
    </article>`).join("") || `<p class="empty-note">没有不完整的观察项。</p>`;
    return `
      <section class="section" aria-labelledby="sec-formal">
        <div class="group-head" id="sec-formal">
          <span class="badge-formal" style="display:inline-flex;align-items:center;padding:3px 10px;border-radius:4px;font-size:0.72rem;font-weight:800;letter-spacing:0.04em;background:#059669;color:#fff">正式预测</span>
          <h2>计入命中校验</h2>
        </div>
        ${formal}
      </section>
      <section class="section" aria-labelledby="sec-learn">
        <h2 class="section-label" id="sec-learn">错误归因 · 学习</h2>
        <div class="learn-grid">${learning || '<p class="empty-note">学习段只服务正式预测复盘；暂无足够对照。</p>'}</div>
        <p class="muted" style="font-size:0.75rem;margin-top:8px">学习段只服务正式预测复盘；观察项不计命中、不进本段主列。</p>
      </section>
      <section class="section" aria-labelledby="sec-observe">
        <div class="group-head" id="sec-observe">
          <span class="badge-observe" style="display:inline-flex;align-items:center;padding:3px 10px;border-radius:4px;font-size:0.72rem;font-weight:700;letter-spacing:0.04em;background:#64748b;color:#fff">观察</span>
          <h2 style="color:#64748b;font-weight:600">规则倾向 · 不进命中率</h2>
        </div>
        ${observations}
        <details class="fold-c">
          <summary>历史证据原文 · 当时全量快照（折叠）</summary>
          <div class="fold-body">证据原文与快照在此折叠；主界面不倾倒分数墙或全市场报告。无原文链接的条目不会假装可点。</div>
        </details>
      </section>`;
  }

  window.StockPmDesk = {
    esc,
    api,
    renderOverview,
    renderStock,
    renderReview,
    bindCarousel,
    eventCard,
    focusRow
  };
})();
