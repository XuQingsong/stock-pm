(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const SYMBOL = decodeURIComponent(location.pathname.split("/")[2] || "").toUpperCase();
  const TABS = ["chart", "review", "earnings", "valuation", "flow", "news-options"];
  const MISSING = "数据源暂未提供";
  const cache = new Map();
  let activeTab = "";
  let chartCleanup = null;

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
  const finite = (value) => value !== null && value !== "" && Number.isFinite(Number(value));
  const num = (value, digits = 2) => finite(value)
    ? Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits })
    : MISSING;
  const compact = (value) => finite(value)
    ? new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 2 }).format(Number(value))
    : MISSING;
  const money = (value) => finite(value) ? `$${num(value)}` : MISSING;
  const pct = (value, sign = true) => finite(value)
    ? `${sign && Number(value) > 0 ? "+" : ""}${Number(value).toFixed(2)}%`
    : MISSING;
  const cls = (value) => !finite(value) ? "" : Number(value) > 0 ? "up" : Number(value) < 0 ? "down" : "";
  const dateText = (value, time = false) => {
    if (!value) return MISSING;
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return esc(value);
    return d.toLocaleString("zh-CN", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      ...(time ? { hour: "2-digit", minute: "2-digit", hour12: false } : {})
    });
  };
  const nyTick = (time, tickMarkType) => {
    if (time && typeof time === "object" && "year" in time) {
      return `${String(time.month).padStart(2, "0")}/${String(time.day).padStart(2, "0")}`;
    }
    const date = new Date(typeof time === "number" ? (time > 1e12 ? time : time * 1000) : Date.parse(time));
    if (tickMarkType <= 2) {
      return date.toLocaleDateString("en-US", { timeZone: "America/New_York", month: "2-digit", day: "2-digit" });
    }
    return date.toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false });
  };
  const nyCrosshair = (time) => {
    if (time && typeof time === "object" && "year" in time) {
      return `${time.year}-${String(time.month).padStart(2, "0")}-${String(time.day).padStart(2, "0")}`;
    }
    const date = new Date(typeof time === "number" ? (time > 1e12 ? time : time * 1000) : Date.parse(time));
    return date.toLocaleString("en-US", {
      timeZone: "America/New_York", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false
    });
  };
  const safeUrl = (value) => {
    try {
      const u = new URL(String(value), location.origin);
      return ["http:", "https:"].includes(u.protocol) ? esc(u.href) : "#";
    } catch (_) { return "#"; }
  };
  const api = async (path) => {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`请求失败（${response.status}）`);
    return response.json();
  };
  const softApi = (path, fallback) => api(path).catch(() => fallback);
  const endpoint = (tail) => `/api/stock/${encodeURIComponent(SYMBOL)}/${tail}`;
  const loading = () => { $("tab-content").innerHTML = '<div class="state loading"><span class="spinner"></span>正在加载…</div>'; };
  const empty = (message = "暂无数据") => `<div class="empty-note">${esc(message)}</div>`;
  const metric = (label, value, note = "", disabled = false) =>
    `<div class="metric${disabled ? " disabled" : ""}"><span>${esc(label)}</span><strong>${esc(value)}</strong>${note ? `<small>${esc(note)}</small>` : ""}</div>`;
  const first = (obj, keys) => {
    for (const key of keys) if (obj && obj[key] !== null && obj[key] !== undefined) return obj[key];
    return null;
  };

  async function loadHeader() {
    if (!SYMBOL) { location.replace("/"); return; }
    $("symbol").textContent = SYMBOL;
    document.title = `Stock PM · ${SYMBOL}`;
    const [watch, snapshots, overview] = await Promise.all([
      softApi("/api/watchlist", []),
      softApi(`/api/market/snapshot?symbols=${encodeURIComponent(SYMBOL)}`, []),
      softApi(endpoint("overview"), {})
    ]);
    const metadata = watch.find((row) => String(row.symbol).toUpperCase() === SYMBOL) || {};
    const snapshot = snapshots.find((row) => String(row.symbol).toUpperCase() === SYMBOL) || snapshots[0] || {};
    const technical = overview.technical || {};
    const valuation = overview.valuation || {};
    const quality = snapshot.quote_quality || {};
    const switcher = $("symbol-switcher");
    switcher.innerHTML = watch.length
      ? watch.map((row) => `<option value="${esc(row.symbol)}"${String(row.symbol).toUpperCase() === SYMBOL ? " selected" : ""}>${esc(row.symbol)}</option>`).join("")
      : `<option value="${esc(SYMBOL)}">${esc(SYMBOL)}</option>`;
    switcher.addEventListener("change", () => {
      location.href = `/stock/${encodeURIComponent(switcher.value)}${location.hash || "#chart"}`;
    });
    $("name").textContent = metadata.name || "未收录名称";
    $("metadata").textContent = [metadata.primary_exchange, metadata.sector].filter(Boolean).join(" · ") || "交易所与行业信息暂缺";
    $("themes").innerHTML = (metadata.themes || []).map((theme) => `<span class="chip">${esc(theme)}</span>`).join("");

    const conclusion = quality.conclusion_price;
    const liveHidden = quality.hide_last_price;
    const price = liveHidden ? conclusion : (first(snapshot, ["displayed_last_price", "last_price", "price", "close_price"]) ?? conclusion ?? technical.close_price);
    const prior = first(snapshot, ["prior_close", "previous_close"]) ?? quality.prior_close;
    const change = liveHidden ? null : first(snapshot, ["change", "price_change"]);
    const changePct = liveHidden ? null : (first(snapshot, ["change_pct", "price_change_pct"])
      ?? (finite(price) && finite(prior) && Number(prior) !== 0 ? (Number(price) / Number(prior) - 1) * 100 : null));
    $("last-price").textContent = money(price);
    $("last-price").className = cls(changePct);
    $("price-change").className = cls(changePct);
    const delayMark = quality.status === "delayed" || quality.delayed ? "延迟行情" : (quality.label || "");
    $("price-change").textContent = liveHidden
      ? (quality.label || MISSING)
      : finite(change)
        ? `${Number(change) > 0 ? "+" : ""}${num(change)}  ${pct(changePct)}`
        : `${pct(changePct)}${delayMark ? ` · ${delayMark}` : ""}`;
    const highDistance = first(technical, ["distance_52w_high_pct"]) ?? first(snapshot, ["distance_52w_high_pct"]);
    const lowDistance = first(technical, ["distance_52w_low_pct"]) ?? first(snapshot, ["distance_52w_low_pct"]);
    const asOf = first(snapshot, ["as_of", "updated_at", "bar_time"]) ?? technical.bar_time;
    const source = first(snapshot, ["source", "data_source"]) ?? first(technical, ["source", "data_source"]);
    const cells = [
      ["成交量", compact(first(snapshot, ["volume", "day_volume"]) ?? technical.volume)],
      ["量比", finite(technical.volume_ratio_20d) ? `${num(technical.volume_ratio_20d)}x` : MISSING],
      ["总市值", compact(first(snapshot, ["market_cap"]) ?? valuation.market_cap)],
      ["PE TTM", num(first(snapshot, ["pe_ttm"]) ?? valuation.pe_ttm)],
      ["RSI 14", num(first(snapshot, ["rsi14"]) ?? technical.rsi14)],
      ["距52周高", pct(highDistance, false)],
      ["距52周低", pct(lowDistance, false)],
      ["数据时间", dateText(asOf, true), true],
      ["报价质量", quality.label || MISSING],
      ["结论价来源", quality.conclusion_source === "review_close" ? "复盘收盘" : quality.conclusion_source === "prior_close" ? "昨收" : quality.conclusion_source === "last_price" ? "现价" : MISSING],
      ["数据源", source || MISSING]
    ];
    $("quote-grid").innerHTML = cells.map(([label, value, wide]) =>
      `<div class="quote-cell${wide ? " wide" : ""}"><span>${esc(label)}</span><b>${esc(value)}</b></div>`
    ).join("");
  }

  function normalizeTime(value) {
    if (typeof value === "number") return value > 1e12 ? Math.floor(value / 1000) : value;
    const ms = Date.parse(value);
    return Number.isNaN(ms) ? String(value).slice(0, 10) : Math.floor(ms / 1000);
  }

  async function renderChart() {
    const interval = cache.get("chart-interval") || "1d";
    const [payload, profile] = await Promise.all([
      api(`${endpoint("chart")}?interval=${encodeURIComponent(interval)}&limit=260`),
      softApi(`${endpoint("volume-profile")}?lookback=60`, {})
    ]);
    const envelope = Array.isArray(payload) ? { bars: payload, interval, source: "", delayed: null, as_of: null } : payload;
    const bars = envelope.bars || [];
    $("tab-content").innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <div><h2>价格与成交量</h2><div class="subline" id="chart-status">${esc(envelope.interval || interval)} · ${esc(envelope.source || MISSING)} · ${envelope.delayed == null ? "延迟信息暂缺" : envelope.delayed ? "延迟行情" : "实时/非延迟"} · 截至 ${dateText(envelope.as_of, true)}</div></div>
          <div class="toolbar" id="chart-toolbar">
            ${["1m", "5m", "15m", "60m", "1d", "1w", "1M"].map((it) => `<button class="btn${it === interval ? " active" : ""}" data-interval="${it}">${it}</button>`).join("")}
          </div>
        </div>
        <div class="toolbar">
          ${[["ma5", "#e59a18"], ["ma20", "#1976d2"], ["ma50", "#7a55c7"], ["ma200", "#00a87b"]].map(([key, color]) => `<label class="ma-toggle" style="--ma:${color}"><input type="checkbox" data-ma="${key}" checked>${key.toUpperCase()}</label>`).join("")}
          <span class="muted">本周期 MA5/20/50/200 · 分钟图额外叠加日线 MA50/MA200</span>
        </div>
        <div class="chart-wrap"><div id="price-chart" class="price-chart"></div>${bars.length ? "" : '<div class="chart-empty">该周期暂无K线数据</div>'}</div>
        <div class="legend-row"><span><i style="background:#00a87b"></i>上涨</span><span><i style="background:#e44b5f"></i>下跌</span><span><i style="background:#d79000"></i>POC</span><span><i style="background:#1976d2"></i>支撑</span><span><i style="background:#e44b5f"></i>压力</span></div>
      </section>
      <section class="panel"><div class="panel-head"><div><h2>KDJ</h2><div class="subline">K / D / J 随所选周期变化</div></div></div><div class="chart-wrap"><div id="kdj-chart" class="kdj-chart"></div>${bars.length ? "" : '<div class="chart-empty">暂无 KDJ 数据</div>'}</div></section>`;
    $("chart-toolbar").addEventListener("click", (event) => {
      const button = event.target.closest("[data-interval]");
      if (!button || button.dataset.interval === interval) return;
      cache.set("chart-interval", button.dataset.interval);
      loading();
      disposeCharts();
      renderChart().catch(showTabError);
    });
    if (!bars.length) return;
    if (!window.LightweightCharts) throw new Error("图表组件加载失败，请检查网络后重试");
    buildLightweightCharts(bars, profile, envelope);
  }

  function buildLightweightCharts(rows, profile, envelope) {
    const chartOptions = {
      layout: { background: { color: "#ffffff" }, textColor: "#64717d" },
      grid: { vertLines: { color: "#edf0f2" }, horzLines: { color: "#edf0f2" } },
      rightPriceScale: { borderColor: "#dfe5e9" },
      timeScale: {
        borderColor: "#dfe5e9",
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time, tickMarkType) => nyTick(time, tickMarkType)
      },
      localization: { locale: "en-US", timeFormatter: nyCrosshair },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal }
    };
    const priceHost = $("price-chart");
    const kdjHost = $("kdj-chart");
    const priceChart = LightweightCharts.createChart(priceHost, { ...chartOptions, width: priceHost.clientWidth, height: priceHost.clientHeight });
    const kdjChart = LightweightCharts.createChart(kdjHost, { ...chartOptions, width: kdjHost.clientWidth, height: kdjHost.clientHeight });
    const candle = priceChart.addCandlestickSeries({ upColor: "#00a87b", downColor: "#e44b5f", borderVisible: false, wickUpColor: "#00a87b", wickDownColor: "#e44b5f", priceScaleId: "right" });
    const volume = priceChart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "volume", lastValueVisible: false, priceLineVisible: false });
    priceChart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    const validRows = rows.filter((row) => finite(row.open_price) && finite(row.high_price) && finite(row.low_price) && finite(row.close_price));
    candle.setData(validRows.map((row) => ({ time: normalizeTime(row.bar_time), open: Number(row.open_price), high: Number(row.high_price), low: Number(row.low_price), close: Number(row.close_price) })));
    volume.setData(validRows.map((row) => ({ time: normalizeTime(row.bar_time), value: Number(row.volume || 0), color: Number(row.close_price) >= Number(row.open_price) ? "#00a87b66" : "#e44b5f66" })));
    const colors = { ma5: "#e59a18", ma20: "#1976d2", ma50: "#7a55c7", ma200: "#00a87b" };
    const maSeries = {};
    Object.entries(colors).forEach(([key, color]) => {
      const series = priceChart.addLineSeries({ color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      series.setData(rows.filter((row) => finite(row[key])).map((row) => ({ time: normalizeTime(row.bar_time), value: Number(row[key]) })));
      maSeries[key] = series;
    });
    document.querySelectorAll("[data-ma]").forEach((input) => input.addEventListener("change", () => {
      maSeries[input.dataset.ma].applyOptions({ visible: input.checked });
    }));
    const line = (price, title, color, style = LightweightCharts.LineStyle.Dashed) => {
      if (finite(price)) candle.createPriceLine({ price: Number(price), color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title });
    };
    line(profile.poc, "POC", "#d79000", LightweightCharts.LineStyle.Solid);
    (profile.support_levels || []).slice(0, 3).forEach((value, i) => line(value, `S${i + 1}`, "#1976d2"));
    (profile.resistance_levels || []).slice(0, 3).forEach((value, i) => line(value, `R${i + 1}`, "#e44b5f"));
    const dailyMa = (envelope && envelope.daily_ma) || {};
    if (envelope && ["1m", "5m", "15m", "60m"].includes(envelope.interval)) {
      line(dailyMa.ma50, "日MA50", "#7a55c7", LightweightCharts.LineStyle.Solid);
      line(dailyMa.ma200, "日MA200", "#00a87b", LightweightCharts.LineStyle.Dashed);
    }
    [["k", "#1976d2"], ["d", "#d79000"], ["j", "#7a55c7"]].forEach(([key, color]) => {
      const series = kdjChart.addLineSeries({ color, lineWidth: key === "j" ? 1 : 2, priceLineVisible: false, lastValueVisible: true });
      series.setData(rows.filter((row) => finite(row[key])).map((row) => ({ time: normalizeTime(row.bar_time), value: Number(row[key]) })));
    });
    const syncRange = (source, target) => source.timeScale().subscribeVisibleLogicalRangeChange((range) => { if (range) target.timeScale().setVisibleLogicalRange(range); });
    syncRange(priceChart, kdjChart); syncRange(kdjChart, priceChart);
    priceChart.timeScale().fitContent(); kdjChart.timeScale().fitContent();
    const observer = new ResizeObserver(() => {
      priceChart.applyOptions({ width: priceHost.clientWidth, height: priceHost.clientHeight });
      kdjChart.applyOptions({ width: kdjHost.clientWidth, height: kdjHost.clientHeight });
    });
    observer.observe(priceHost); observer.observe(kdjHost);
    chartCleanup = () => { observer.disconnect(); priceChart.remove(); kdjChart.remove(); chartCleanup = null; };
  }

  function disposeCharts() { if (chartCleanup) chartCleanup(); }

  function comparisonCard(label, actual, estimate, surprise) {
    const available = finite(actual) || finite(estimate);
    const status = finite(surprise) ? Number(surprise) >= 0 ? "beat" : "miss" : "";
    const statusText = !finite(surprise)
      ? (finite(actual) || finite(estimate) ? "预期未提供" : MISSING)
      : Number(surprise) >= 0 ? "超预期" : "低于预期";
    return `<div class="comparison">
      <div class="comparison-head"><h3>${esc(label)}</h3><span class="badge ${status}">${esc(statusText)}</span></div>
      <div class="actual-estimate"><div><span>实际</span><b>${available && finite(actual) ? esc(num(actual)) : MISSING}</b></div><div><span>预期</span><b>${available && finite(estimate) ? esc(num(estimate)) : MISSING}</b></div></div>
      <div class="subline">Surprise：${pct(surprise)}</div>
    </div>`;
  }

  async function renderEarnings() {
    const data = await api(endpoint("earnings/summary"));
    const latest = data.latest || {};
    const history = data.history || [];
    const provider = data.provider || {};
    const fields = (prefix) => [
      first(latest, [`${prefix}_actual`, `actual_${prefix}`]),
      first(latest, [`${prefix}_estimate`, `estimate_${prefix}`]),
      first(latest, [`${prefix}_surprise_pct`, `${prefix}_surprise`])
    ];
    const eps = fields("eps"), revenue = fields("revenue"), income = fields("net_income");
    const thesis = data.thesis || {};
    const year = thesis.earnings_year || {};
    const growth = thesis.growth || {};
    $("tab-content").innerHTML = `
      <section class="panel hero">
        <div class="muted">最新财报 · ${esc(provider.name || MISSING)}${provider.status ? ` · ${esc(provider.status)}` : ""}</div>
        <h2>${esc(first(latest, ["fiscal_period", "quarter"]) || MISSING)}</h2>
        <div class="hero-stats"><div><span>报告日</span><b>${dateText(first(latest, ["report_date", "reported_at"]))}</b></div><div><span>平均绝对波动</span><b>${pct(data.avg_abs_move_pct, false)}</b></div><div><span>盘后 1 日</span><b class="${cls(latest.post_1d_return_pct)}">${pct(latest.post_1d_return_pct)}</b></div></div>
        ${provider.message ? `<div class="subline">${esc(provider.message)}</div>` : ""}
      </section>
      <section class="panel"><div class="section-label">一年结论</div>
        <div class="metric-grid">${metric("一年涨跌", pct(thesis.return_1y_pct))}${metric("距52周高", pct(thesis.distance_52w_high_pct, false))}${metric("EPS 超预期", year.eps_scored ? `${year.eps_beats}/${year.eps_scored}` : MISSING)}${metric("营收超预期", year.revenue_scored ? `${year.revenue_beats}/${year.revenue_scored}` : MISSING)}${metric("营收同比", pct(growth.revenue_yoy_pct))}${metric("增长阶段", growth.phase || MISSING)}${metric("同主题对比", growth.vs_peers || MISSING)}${metric("相对自身估值", (thesis.valuation || {}).label || MISSING)}</div>
        <div class="subline">行业成长期只比较同主题自选同比，不是行业 TAM。缺预期的季度不计入超预期次数。</div>
      </section>
      <section class="grid three">${comparisonCard("营收", ...revenue)}${comparisonCard("净利润", ...income)}${comparisonCard("每股收益 EPS", ...eps)}</section>
      <section class="panel"><div class="section-label">规则摘要</div>${(data.highlights || []).length ? `<ul class="highlights">${data.highlights.slice(0, 3).map((text) => `<li>${esc(text)}</li>`).join("")}</ul>` : empty(MISSING)}</section>
      <section class="panel"><div class="panel-head"><div><h2>历史财报后表现</h2><div class="subline">价格反应不代表未来表现</div></div></div>
        ${history.length ? `<div class="table-wrap"><table><thead><tr><th>报告日</th><th>财季</th><th>EPS 实际/预期</th><th>营收实际/预期</th><th>后1日</th><th>后5日</th><th>后20日</th></tr></thead><tbody>${history.map((row) => `<tr><td>${dateText(row.report_date)}</td><td>${esc(row.fiscal_period || MISSING)}</td><td>${esc(num(row.eps_actual))} / ${esc(num(row.eps_estimate))}</td><td>${esc(num(row.revenue_actual))} / ${esc(num(row.revenue_estimate))}</td>${["post_1d_return_pct", "post_5d_return_pct", "post_20d_return_pct"].map((key) => `<td class="${cls(row[key])}"><div class="move-cell"><i class="move-bar" style="width:${Math.min(70, Math.abs(Number(row[key] || 0)) * 3)}px;background:${Number(row[key]) >= 0 ? "var(--green)" : "var(--red)"}"></i>${pct(row[key])}</div></td>`).join("")}</tr>`).join("")}</tbody></table></div>` : empty("暂无历史财报表现")}
      </section>`;
  }

  function valuationSvg(series, metrics) {
    const rows = series.filter((row) => finite(row.pe_ttm));
    if (!rows.length) return empty("暂无 PE 历史数据");
    const width = 900, height = 300, pad = 42;
    const values = rows.map((row) => Number(row.pe_ttm));
    const low = finite(metrics.pe_low) ? Number(metrics.pe_low) : Math.min(...values);
    const high = finite(metrics.pe_high) ? Number(metrics.pe_high) : Math.max(...values);
    const min = Math.min(low, ...values), max = Math.max(high, ...values);
    const span = max - min || 1;
    const x = (i) => pad + i * (width - pad * 2) / Math.max(1, rows.length - 1);
    const y = (v) => height - pad - (v - min) * (height - pad * 2) / span;
    const points = rows.map((row, i) => `${x(i)},${y(Number(row.pe_ttm))}`).join(" ");
    const bandTop = y(high), bandBottom = y(low);
    return `<svg class="valuation-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="PE TTM 历史走势">
      <rect x="${pad}" y="${Math.min(bandTop, bandBottom)}" width="${width - pad * 2}" height="${Math.max(2, Math.abs(bandBottom - bandTop))}" fill="#1976d213"/>
      <line x1="${pad}" x2="${width - pad}" y1="${y(low)}" y2="${y(low)}" stroke="#8fa4b3" stroke-dasharray="4 4"/><line x1="${pad}" x2="${width - pad}" y1="${y(high)}" y2="${y(high)}" stroke="#8fa4b3" stroke-dasharray="4 4"/>
      <polyline fill="none" stroke="#1976d2" stroke-width="2.5" points="${points}"/>
      <text x="5" y="${y(high) + 4}" class="svg-label">${esc(num(high))}</text><text x="5" y="${y(low) + 4}" class="svg-label">${esc(num(low))}</text>
      <text x="${pad}" y="${height - 10}" class="svg-label">${dateText(rows[0].captured_at)}</text><text x="${width - pad}" y="${height - 10}" text-anchor="end" class="svg-label">${dateText(rows[rows.length - 1].captured_at)}</text>
    </svg>`;
  }

  async function renderValuation() {
    const data = await api(endpoint("valuation/history"));
    const current = data.current || {};
    const metrics = data.metrics || {};
    const series = data.series || [];
    const last = series[series.length - 1] || {};
    const pe = first(current, ["pe_ttm"]) ?? last.pe_ttm;
    const pb = first(current, ["price_to_book"]) ?? last.price_to_book;
    const ps = first(current, ["price_to_sales"]) ?? last.price_to_sales;
    const coverage = data.coverage || {};
    const coverageText = coverage.count
      ? `${coverage.count} 个快照${coverage.band_ready ? "" : "（样本不足 8，暂不绘制分位区间）"}`
      : MISSING;
    $("tab-content").innerHTML = `
      <section class="panel"><div class="panel-head"><div><h2>估值概览</h2><div class="subline">${esc(coverageText)}</div></div></div>
        <div class="metric-grid">${metric("PE TTM", num(pe))}${metric("自身一年分位", finite(metrics.pe_percentile) ? pct(metrics.pe_percentile, false) : MISSING)}${metric("相对自身", metrics.label || MISSING)}${metric("样本数", num(metrics.samples, 0))}${metric("历史区间", finite(metrics.pe_low) || finite(metrics.pe_high) ? `${num(metrics.pe_low)} – ${num(metrics.pe_high)}` : MISSING)}${metric("市净率 PB", num(pb), finite(pb) ? "" : "未提供，不做推算", !finite(pb))}${metric("市销率 PS", num(ps), finite(ps) ? "" : "未提供，不做推算", !finite(ps))}</div>
        ${metrics.basis ? `<div class="disclaimer">${esc(metrics.basis)}。Forward PE / 目标价未提供时不做贵贱判断。</div>` : ""}
      </section>
      <section class="panel"><div class="panel-head"><div><h2>PE TTM 历史</h2><div class="subline">阴影区为接口提供的低/高区间；缺失时仅展示实际序列范围</div></div></div>${valuationSvg(series, metrics)}</section>`;
  }

  function profileSvg(profile) {
    const buckets = (profile.buckets || []).filter((row) => finite(row.price) && finite(row.volume));
    if (!buckets.length) return empty("暂无筹码分布数据");
    const width = 760, rowH = 17, pad = 62, height = Math.max(270, buckets.length * rowH + 30);
    const maxVolume = Math.max(...buckets.map((row) => Number(row.volume)), 1);
    const prices = buckets.map((row) => Number(row.price));
    const minPrice = Math.min(...prices), maxPrice = Math.max(...prices);
    const py = (price) => 15 + (maxPrice - Number(price)) / (maxPrice - minPrice || 1) * (height - 35);
    const marker = (value, label, color) => finite(value) ? `<line x1="${pad}" x2="${width - 4}" y1="${py(value)}" y2="${py(value)}" stroke="${color}" stroke-width="1.5"/><text x="${width - 7}" y="${py(value) - 3}" text-anchor="end" class="svg-value">${esc(label)} ${esc(num(value))}</text>` : "";
    return `<svg class="profile-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="成交量筹码分布">
      ${buckets.map((row) => { const y = py(row.price); return `<text x="2" y="${y + 4}" class="svg-label">${esc(num(row.price))}</text><rect x="${pad}" y="${y - 6}" width="${Math.max(2, Number(row.volume) / maxVolume * (width - pad - 10))}" height="12" rx="2" fill="${Number(row.price) === Number(profile.poc) ? "#d79000" : "#78a8c8"}"><title>${esc(num(row.volume_pct))}% · ${esc(compact(row.volume))}</title></rect>`; }).join("")}
      ${marker(profile.current_price, "现价", "#17202a")}${marker(profile.poc, "POC", "#d79000")}
      ${(profile.support_levels || []).map((value, i) => marker(value, `S${i + 1}`, "#1976d2")).join("")}
      ${(profile.resistance_levels || []).map((value, i) => marker(value, `R${i + 1}`, "#e44b5f")).join("")}
    </svg>`;
  }

  async function renderFlow() {
    const [profile, flow] = await Promise.all([
      api(`${endpoint("volume-profile")}?lookback=60`),
      api(`${endpoint("capital-flow")}?days=5`)
    ]);
    const tiers = flow.tiers || [], timeline = flow.timeline || [];
    const maxNet = Math.max(1, ...timeline.map((row) => Math.abs(Number(row.net_notional || 0))));
    $("tab-content").innerHTML = `
      <div class="disclaimer prominent">筹码分布基于 OHLCV估算；大额成交方向由 tick rule推断。分层仅按成交金额划分，不代表机构/散户身份，也不构成投资建议。</div>
      <div class="grid two">
        <section class="panel"><div class="panel-head"><div><h2>成交量筹码分布</h2><div class="subline">${esc(profile.lookback || 60)} 日 · ${esc(profile.basis || "OHLCV估算")}</div></div><div>${metric("获利盘比例", pct(profile.volume_below_pct, false))}</div></div>${profileSvg(profile)}<div class="legend-row"><span>价值区 ${money(profile.value_low)} – ${money(profile.value_high)}</span><span>POC ${money(profile.poc)}</span></div></section>
        <section class="panel"><div class="panel-head"><div><h2>大额成交买卖推断</h2><div class="subline">${esc(flow.flow_label || MISSING)}</div></div></div>
          ${tiers.length ? tiers.map((tier) => { const buy = Number(tier.buy_notional || 0), sell = Number(tier.sell_notional || 0), total = buy + sell || 1; return `<div class="tier-row"><span>${esc(tier.name || MISSING)}</span><div class="tier-bars" title="买 ${esc(compact(buy))} / 卖 ${esc(compact(sell))}"><i class="buy-bar" style="width:${buy / total * 100}%"></i><i class="sell-bar" style="width:${sell / total * 100}%"></i></div><b class="${cls(tier.net_notional)}">${compact(tier.net_notional)}</b></div><div class="subline">${finite(tier.min_notional) ? compact(tier.min_notional) : "0"} – ${finite(tier.max_notional) ? compact(tier.max_notional) : "以上"} · ${num(tier.count, 0)} 笔</div>`; }).join("") : empty("暂无分层成交数据")}
          <div class="legend-row"><span><i style="background:var(--green)"></i>推断买入</span><span><i style="background:var(--red)"></i>推断卖出</span></div>
        </section>
      </div>
      <div class="grid two">
        <section class="panel"><div class="panel-head"><div><h2>近 5 日资金时间线</h2><div class="subline">中心线左侧为净卖出，右侧为净买入</div></div></div>${timeline.length ? timeline.map((row) => { const net = Number(row.net_notional || 0), width = Math.abs(net) / maxNet * 50; return `<div class="timeline-row"><span>${dateText(row.date)}</span><div class="timeline-track"><i style="${net >= 0 ? "left:50%" : `left:${50 - width}%`};width:${width}%;background:${net >= 0 ? "var(--green)" : "var(--red)"}"></i></div><b class="${cls(net)}">${compact(net)}</b></div>`; }).join("") : empty("暂无资金时间线")}</section>
        <section class="panel"><div class="panel-head"><div><h2>量价资金指标</h2><div class="subline">指标基于可获得成交量计算</div></div></div><div class="metric-grid">${metric("CMF 20", num(flow.cmf20, 4))}${metric("OBV 5日标准化", num(flow.obv_5d_normalized, 4))}${metric("资金标签", flow.flow_label || MISSING)}</div><div class="disclaimer">${esc(flow.disclaimer || "tick rule 推断存在误差，不能据此识别交易者身份。")}</div></section>
      </div>`;
  }

  function optionWall(options) {
    if (!options.length) return empty("暂无期权墙数据");
    const max = Math.max(1, ...options.flatMap((row) => [Number(row.call_open_interest || 0), Number(row.put_open_interest || 0)]));
    return `<div class="subline">到期 ${dateText(options[0].expiration_date)} · 标的现价 ${money(options[0].spot_price)}</div>${options.map((row) => {
      const call = Number(row.call_open_interest || 0), put = Number(row.put_open_interest || 0);
      return `<div class="option-row"><b>${money(row.strike)}</b><div><span class="subline">Call ${compact(call)}</span><div class="oi"><i style="width:${call / max * 100}%;background:var(--green)"></i></div></div><div><span class="subline">Put ${compact(put)}</span><div class="oi"><i style="width:${put / max * 100}%;background:var(--red)"></i></div></div></div>`;
    }).join("")}`;
  }

  async function renderReview(didRetry) {
    const rows = await softApi(endpoint("reviews"), []);
    const review = rows[0];
    const notes = await softApi(endpoint("review-notes"), []);
    const note = notes[0];
    if (!review && !note) {
      $("tab-content").innerHTML = `${empty("当日复盘尚未生成")} <div class="disclaimer">也可打开 <a href="/review">每日复盘</a>。</div>`;
      return;
    }
    const date = String((review && review.review_date) || (note && note.as_of_date) || "").slice(0, 10);
    let briefing = await softApi(`/api/briefing?date=${encodeURIComponent(date)}`, { rows: [] });
    let row = (briefing.rows || []).find((item) => String(item.symbol).toUpperCase() === SYMBOL) || review || {};
    const reviewSafe = review || {};
    const noteSafe = note || row.review_note || {};
    const status = row.llm_status || reviewSafe.llm_status || null;
    if (!didRetry && status === "quota_exhausted") {
      $("tab-content").innerHTML = '<div class="state loading"><span class="spinner"></span>模型额度已用尽，正在重新请求生成…充值后刷新即可。</div>';
      await fetch(`/api/reviews/retry-llm?date=${encodeURIComponent(date)}&symbol=${encodeURIComponent(SYMBOL)}`, {
        method: "POST",
        headers: { Accept: "application/json" }
      }).catch(() => null);
      return renderReview(true);
    }
    const quota = status === "quota_exhausted";
    const llmMissing = Boolean(status) && status !== "ok";
    const context = row.context || reviewSafe.context || {};
    const news = context.news || [];
    const macro = context.macro || [];
    const prior = row.prior_outcome;
    const llmNote = !status
      ? ""
      : quota
        ? `<div class="disclaimer prominent">模型额度已用尽。请充值后刷新本页，系统会自动重新生成「为何走」和明日看法。</div>`
        : llmMissing
          ? `<div class="disclaimer prominent">${esc(row.llm_error || reviewSafe.llm_error || `解释与明日看法未生成（${status}）`)}</div>`
          : `<div class="subline">结论已生成。${row.llm_generated_at ? `上次生成 ${esc(String(row.llm_generated_at).replace("T", " ").slice(0, 16))} UTC。` : ""}量价、新闻或宏观变化后才会再生成。</div>`;
    $("tab-content").innerHTML = `
      <section class="panel hero">
        <div class="muted">复盘总结 · ${dateText(noteSafe.as_of_date || reviewSafe.review_date)}</div>
        <h2>${esc(noteSafe.summary || row.row_thesis || row.health || reviewSafe.breakout_status || MISSING)}</h2>
        <p class="review-body">${esc(noteSafe.explanation || "解释不了：消息与情绪依据不足，不硬编诱多、转势、吸筹或逃跑。")}</p>
        <div class="hero-stats">
          <div><span>结论价</span><b>${money(row.conclusion_price ?? reviewSafe.close_price)}</b></div>
          <div><span>昨盘</span><b>${esc((row.tape_analysis && row.tape_analysis.one_liner) || row.tape_half || reviewSafe.short_trend || MISSING)}</b></div>
          <div><span>均线</span><b>${esc(row.ma_position || MISSING)}</b></div>
          <div><span>5日</span><b class="${cls(row.return_5d_pct)}">${pct(row.return_5d_pct)}</b></div>
        </div>
        <div class="subline">白话总结来自昨盘。预测见上方壳：时间窗口 + 涨跌边界，缺则点名缺哪一项。完整列表见 <a href="/review?date=${encodeURIComponent(date)}" style="color:inherit">每日复盘</a>。</div>
      </section>
      ${llmNote}
      <details class="fold" data-zone="C"><summary>折叠材料（规则摘要 / 新闻原句 / 模型草稿，不代替结论）</summary>
      <section class="panel"><p class="review-body">${esc(reviewSafe.summary || MISSING)}</p>
        <div class="metric-grid">${metric("支撑", money(reviewSafe.support_price))}${metric("压力", money(reviewSafe.resistance_price))}${metric("突破状态", reviewSafe.breakout_status || MISSING)}${metric("规则偏向", row.rule_bias || MISSING)}</div>
      </section>
      <section class="panel"><h2>可能解释走势的资料</h2>
        ${news.length || macro.length ? news.map((item) => {
          const copy = window.stockPmCopy || {};
          const head = copy.newsHeadline ? copy.newsHeadline(item) : `<b>${esc(item.headline || MISSING)}</b>`;
          const line = copy.newsStanceLine ? copy.newsStanceLine(item) : (item.stance_line || "");
          return `<div class="news-item">${head}<div class="subline news-stance">${esc(line)}</div></div>`;
        }).join("") + macro.map((item) => `<div class="news-item"><b>${esc(item.name || MISSING)}</b><div class="subline">${esc(item.narrative || "")}</div></div>`).join("") : empty("当日没有可挂上的新闻或宏观")}
      </section>
      <section class="panel"><h2>模型：为何这样走</h2><p class="review-body">${esc(row.llm_why || reviewSafe.llm_why || "未生成")}</p></section>
      <section class="panel"><h2>自动明日看法 <span class="legacy-tag">规则对照</span></h2><p class="review-body">${esc(row.llm_outlook || reviewSafe.llm_outlook || "未生成")}</p><div class="subline">偏向 ${esc(row.active_bias || row.llm_bias || MISSING)} · 来源 ${esc(row.active_bias_source || "rule")} · 不是时间窗口或涨跌边界</div></section>
      </details>
      <section class="panel"><h2>折叠：可选备注</h2>
        <div class="toolbar"><select id="user-bias"><option value=""${row.user_bias ? "" : " selected"}>沿用自动判断</option>${["偏多", "中性", "偏空", "观望"].map((value) => `<option value="${value}"${row.user_bias === value ? " selected" : ""}>${value}</option>`).join("")}</select>
          <button class="btn" id="save-review">保存备注</button><span class="muted" id="save-status">${row.user_note || row.user_outlook || row.user_bias ? "已有备注" : "未写备注"}</span></div>
        <p class="subline" style="margin-top:8px">看法（留空则沿用模型/规则）</p>
        <textarea id="user-outlook" style="width:100%;min-height:72px">${esc(row.user_outlook || "")}</textarea>
        <p class="subline">备注</p>
        <textarea id="user-note" style="width:100%;min-height:56px">${esc(row.user_note || "")}</textarea>
        <div class="subline" style="margin-top:8px">上一判断：${prior ? `${esc(prior.bias || "—")} → ${esc(prior.outcome_vs_bias || "—")}（${pct(prior.outcome_return_pct)}）` : "暂无对照"}</div>
      </section>`;
    $("save-review").addEventListener("click", async () => {
      $("save-status").textContent = "保存中…";
      try {
        const response = await fetch(`/api/reviews/${encodeURIComponent(SYMBOL)}/${date}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({
            user_bias: $("user-bias").value || null,
            user_outlook: $("user-outlook").value,
            user_note: $("user-note").value
          })
        });
        if (!response.ok) throw new Error("保存失败");
        $("save-status").textContent = "已保存";
      } catch (error) {
        $("save-status").textContent = error.message || "保存失败";
      }
    });
  }

  function newsImpactBlock(item) {
    const copy = window.stockPmCopy || {};
    const names = item.theme_names || [];
    const chips = names.map((theme) => `<span class="chip">${esc(theme)}</span>`).join("");
    const head = copy.newsHeadline ? copy.newsHeadline(item) : `<b>${esc(item.headline || MISSING)}</b>`;
    const line = copy.newsStanceLine ? copy.newsStanceLine(item) : (item.stance_line || "分歧 · 因为规则未映射到可核对依据");
    return `<article class="news-item">${head}<div class="chips">${chips}</div><div class="subline news-stance">${esc(line)}</div><div class="news-meta">${dateText(item.published_at, true)} · ${esc(item.source || MISSING)}</div></article>`;
  }

  async function renderNewsOptions() {
    const [news, options] = await Promise.all([
      softApi(endpoint("news"), []), softApi(endpoint("options"), [])
    ]);
    const mapped = news.filter((item) => (item.impacts || []).length);
    const rest = news.filter((item) => !(item.impacts || []).length);
    $("tab-content").innerHTML = `
      <div class="grid two">
        <section class="panel"><div class="panel-head"><div><h2>板块影响</h2><div class="subline">${mapped.length} 条已映射 · 规则标注</div></div></div>
          ${mapped.length ? mapped.map(newsImpactBlock).join("") : empty("近期没有可映射到板块的新闻")}
        </section>
        <div>
          <section class="panel"><div class="panel-head"><div><h2>未覆盖资讯</h2><div class="subline">${rest.length} 条未强制归类</div></div></div>
            ${rest.length ? rest.map(newsImpactBlock).join("") : empty("没有未覆盖新闻")}
          </section>
          <section class="panel"><div class="panel-head"><div><h2>最近到期期权墙</h2><div class="subline">个股墙与全市场期权不是同一口径，不并排当结论</div></div></div>${options.length ? optionWall(options) : empty("期权墙数据暂缺")}</section>
        </div>
      </div>`;
  }

  const renderers = { chart: renderChart, review: renderReview, earnings: renderEarnings, valuation: renderValuation, flow: renderFlow, "news-options": renderNewsOptions };
  function showTabError(error) {
    $("tab-content").innerHTML = `<div class="state error"><b>加载失败</b><span>${esc(error.message || "未知错误")}</span><button class="btn" id="retry-tab">重试</button></div>`;
    $("retry-tab").addEventListener("click", () => activate(activeTab, true));
  }
  async function activate(tab, force = false) {
    if (!TABS.includes(tab)) tab = "chart";
    if (activeTab === tab && !force) return;
    disposeCharts();
    activeTab = tab;
    document.querySelectorAll("[data-tab]").forEach((button) => {
      const selected = button.dataset.tab === tab;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-selected", String(selected));
    });
    if (location.hash !== `#${tab}`) history.replaceState(null, "", `#${tab}`);
    loading();
    try { await renderers[tab](); } catch (error) { showTabError(error); }
  }

  document.querySelector(".tabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-tab]");
    if (button) location.hash = button.dataset.tab;
  });
  window.addEventListener("hashchange", () => activate(location.hash.slice(1)));
  window.addEventListener("beforeunload", disposeCharts);
  Promise.all([
    loadHeader(),
    window.mountStockPmShell ? window.mountStockPmShell({ symbol: SYMBOL }) : Promise.resolve()
  ]).finally(() => activate(location.hash.slice(1) || "chart"));
})();
