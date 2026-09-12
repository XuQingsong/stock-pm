(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  async function loadCenter() {
    const root = $("event-center");
    const coverNode = $("event-coverage");
    if (!root) return;
    try {
      const response = await fetch("/api/events", { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`请求失败（${response.status}）`);
      const payload = await response.json();
      const ui = window.StockPmEvents;
      const cover = ui.renderCoverage(payload.coverage || {});
      if (coverNode) {
        coverNode.innerHTML = cover.html;
        coverNode.dataset.googleStatus = cover.googleStatus;
        coverNode.dataset.eventsReady = "1";
      }
      root.className = "";
      root.innerHTML = ui.renderCenter(payload);
      root.dataset.eventsReady = "1";
      root.dataset.eventCount = String((payload.events || []).length);
    } catch (error) {
      root.className = "state error";
      root.dataset.eventsReady = "error";
      root.innerHTML = `<b>事件中心加载失败</b><span>${window.StockPmEvents.esc(error.message || "未知错误")}</span>`;
      root.innerHTML += `<p class="subline">只影响事件链，不影响价格 / 盈利 / 宏观利率。</p>`;
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadCenter);
  } else {
    loadCenter();
  }
})();
