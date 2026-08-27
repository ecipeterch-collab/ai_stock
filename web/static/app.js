const TOKEN_KEY = "ai_stock_token";
const CHART_REFRESH_MS = 10000;

let profitChart = null;
let monthlyPnlChart = null;
let stockChart = null;
let stockChartSeries = null;
let selectedTradeCode = null;
let tradedStocksCache = [];
let chartRefreshTimer = null;
let pendingCommand = null;
let authBlocked = false;
let refreshInFlight = false;

const $ = (id) => document.getElementById(id);

function show(view) {
  $("login-view").classList.toggle("hidden", view !== "login");
  $("dashboard-view").classList.toggle("hidden", view !== "dashboard");
}

function getToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

function setToken(token) {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

async function api(path, options = {}) {
  const isLogin = String(path).startsWith("/api/auth/login");
  if (authBlocked && !isLogin) {
    throw new Error("로그인이 필요합니다.");
  }
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    if (!isLogin) {
      authBlocked = true;
      setToken(null);
      stopChartAutoRefresh();
      show("login");
    }
    throw new Error(data.detail || "로그인이 필요합니다.");
  }
  if (!res.ok) {
    throw new Error(data.detail || `오류 (${res.status})`);
  }
  return data;
}

function formatWon(n) {
  if (n == null) return "—";
  const v = Number(n);
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toLocaleString("ko-KR")}원`;
}

function formatWonPlain(n) {
  if (n == null) return "—";
  return `${Number(n).toLocaleString("ko-KR")}원`;
}

function profitClass(pct) {
  if (pct > 0) return "profit-pos";
  if (pct < 0) return "profit-neg";
  return "";
}

function signedPct(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}`;
}

function renderNewsSessions(data) {
  const wrap = data && data.news_sessions;
  $("news-session-date").textContent = wrap ? wrap.date : "—";
  const sessions = (wrap && wrap.sessions) || {};
  for (const [key, prefix] of [
    ["morning", "news-morning"],
    ["afternoon", "news-afternoon"],
  ]) {
    const sess = sessions[key] || {};
    const valueEl = $(`${prefix}-value`);
    const metaEl = $(`${prefix}-meta`);
    if (!sess.count) {
      valueEl.textContent = "기록 없음";
      valueEl.className = "muted";
      metaEl.textContent = "장중 자동점검이 쌓이면 표시됩니다";
      continue;
    }
    valueEl.textContent = signedPct(sess.avg_sentiment);
    valueEl.className = profitClass(sess.avg_sentiment);
    const blockPct = Math.round((sess.block_ratio || 0) * 100);
    metaEl.textContent =
      `범위 ${signedPct(sess.min_sentiment)}~${signedPct(sess.max_sentiment)} · ` +
      `${sess.count}회 · 매수중단 ${blockPct}%`;
  }
}

function renderMonthlyPnlChart(byMonth) {
  const canvas = $("monthly-pnl-chart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const rows = byMonth || [];

  if (monthlyPnlChart) monthlyPnlChart.destroy();
  if (!rows.length) {
    monthlyPnlChart = null;
    return;
  }

  const labels = rows.map((r) => r.month);
  const values = rows.map((r) => r.net_pnl_krw);
  const colors = values.map((v) =>
    v >= 0 ? "rgba(61, 214, 140, 0.75)" : "rgba(240, 113, 120, 0.75)"
  );

  monthlyPnlChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "월별 순손익",
          data: values,
          backgroundColor: colors,
          borderRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => formatWon(ctx.parsed.y),
          },
        },
      },
      scales: {
        y: {
          ticks: {
            color: "#8b9cb3",
            callback: (v) => `${Math.round(v / 10000)}만`,
          },
          grid: { color: "#2d3a4d" },
        },
        x: {
          ticks: { color: "#8b9cb3" },
          grid: { display: false },
        },
      },
    },
  });
}

function renderAccountSummary(acct, deposit, holdingsEval) {
  const badge = $("account-mode-badge");
  const deltaEl = $("acct-delta-value");
  const deltaPctEl = $("acct-delta-pct");
  const line = $("account-trading-line");
  const settleLine = $("account-settle-line");

  const clearSettle = () => {
    $("acct-d0-value").textContent = "—";
    $("acct-d1-value").textContent = "—";
    $("acct-d2-value").textContent = "—";
    $("acct-holdings-value").textContent = "—";
    if (settleLine) {
      settleLine.textContent = "—";
      settleLine.className = "status-line muted";
    }
  };

  if (!acct || !acct.trading_summary) {
    badge.textContent = "—";
    $("acct-total-value").textContent = "—";
    deltaEl.textContent = "—";
    deltaPctEl.textContent = "";
    $("acct-initial-value").textContent = "—";
    $("acct-trading-net").textContent = "—";
    $("acct-win-rate").textContent = "—";
    $("acct-fees-value").textContent = "—";
    line.textContent = "거래 기록 없음";
    line.className = "status-line muted";
    clearSettle();
    renderMonthlyPnlChart([]);
    return;
  }

  const ts = acct.trading_summary;
  const as = acct.account_summary || {};
  const total = as.total_assets_krw ?? acct.live_totals?.total_assets_krw;
  const delta = as.balance_delta_krw;
  const deltaPct = as.return_on_capital_pct;
  const dep = deposit || {};

  badge.textContent = acct.trade_mode_label || "—";
  $("acct-total-value").textContent = formatWonPlain(total);
  deltaEl.textContent = formatWon(delta);
  deltaEl.className = profitClass(delta);
  deltaPctEl.textContent =
    deltaPct != null ? `(${deltaPct >= 0 ? "+" : ""}${deltaPct}%)` : "";
  deltaPctEl.className = profitClass(deltaPct);

  $("acct-d0-value").textContent = formatWonPlain(dep.cash);
  $("acct-d1-value").textContent = formatWonPlain(dep.d1_cash);
  $("acct-d2-value").textContent = formatWonPlain(dep.d2_cash);
  $("acct-holdings-value").textContent = formatWonPlain(holdingsEval);
  if (settleLine) {
    const buy = dep.d1_buy_exct || 0;
    const sell = dep.d1_sel_exct || 0;
    const gap = (dep.d2_cash || 0) - (dep.cash || 0);
    const parts = [];
    if (sell) parts.push(`오늘 매도 ${formatWonPlain(sell)}`);
    if (buy) parts.push(`오늘 매수 ${formatWonPlain(buy)}`);
    if (gap) parts.push(`D+0↔D+2 차이 ${formatWon(gap)}`);
    settleLine.textContent = parts.length
      ? `${parts.join(" · ")} · D+0은 결제 전 예수금`
      : "D+0은 결제 전 예수금 · 총자산은 D+2+보유";
    settleLine.className = "status-line muted";
  }

  $("acct-initial-value").textContent = formatWonPlain(acct.initial_capital_krw);
  const netEl = $("acct-trading-net");
  netEl.textContent = formatWon(ts.net_pnl_krw);
  netEl.className = profitClass(ts.net_pnl_krw);

  $("acct-win-rate").textContent =
    ts.win_rate_pct != null
      ? `${ts.win_rate_pct}% (${ts.wins}/${ts.count})`
      : "—";

  $("acct-fees-value").textContent = formatWon(-Math.abs(ts.total_fees_krw || 0));

  line.textContent = `완결 ${ts.count}건 · 세전 ${formatWon(ts.gross_pnl_krw)} · 순손익 ${formatWon(ts.net_pnl_krw)}`;
  line.className = `status-line ${profitClass(ts.net_pnl_krw)}`;

  renderMonthlyPnlChart(acct.by_month || []);
}

function destroyStockChart() {
  if (stockChart) {
    stockChart.remove();
    stockChart = null;
    stockChartSeries = null;
  }
}

function renderStockChart(data) {
  const wrap = $("trade-chart-wrap");
  const container = $("stock-candle-chart");
  const tradesList = $("trade-chart-trades");
  const loading = $("trade-chart-loading");

  loading.classList.add("hidden");

  if (data.error) {
    wrap.classList.add("hidden");
    tradesList.innerHTML = `<li class="error">${data.error}</li>`;
    return;
  }

  if (!data.candles || !data.candles.length) {
    wrap.classList.add("hidden");
    tradesList.innerHTML = '<li class="muted">차트 데이터 없음</li>';
    return;
  }

  wrap.classList.remove("hidden");
  destroyStockChart();

  if (typeof LightweightCharts === "undefined") {
    tradesList.innerHTML = '<li class="error">차트 라이브러리 로드 실패</li>';
    return;
  }

  container.innerHTML = "";
  stockChart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: 280,
    layout: {
      background: { color: "#1a2332" },
      textColor: "#8b9cb3",
    },
    grid: {
      vertLines: { color: "#2d3a4d" },
      horzLines: { color: "#2d3a4d" },
    },
    rightPriceScale: { borderColor: "#2d3a4d" },
    timeScale: { borderColor: "#2d3a4d" },
  });

  stockChartSeries = stockChart.addCandlestickSeries({
    upColor: "#3dd68c",
    downColor: "#f07178",
    borderVisible: false,
    wickUpColor: "#3dd68c",
    wickDownColor: "#f07178",
  });
  stockChartSeries.setData(data.candles);

  const markers = (data.markers || []).map((m) => ({
    time: m.time,
    position: m.type === "buy" ? "belowBar" : "aboveBar",
    color:
      m.type === "buy"
        ? "#3d8bfd"
        : m.profit_pct != null && m.profit_pct < 0
          ? "#f07178"
          : "#3dd68c",
    shape: m.type === "buy" ? "arrowUp" : "arrowDown",
    text: m.type === "buy" ? "B" : "S",
  }));
  if (markers.length) {
    stockChartSeries.setMarkers(markers);
  }

  stockChart.timeScale().fitContent();

  tradesList.innerHTML = "";
  const trades = data.trades || [];
  if (!trades.length) {
    tradesList.innerHTML = '<li class="muted">완결 거래 없음 (보유 중)</li>';
    return;
  }
  for (const t of trades.slice().reverse()) {
    const li = document.createElement("li");
    const pct = t.profit_pct != null ? fmtPct(t.profit_pct) : "—";
    li.innerHTML = `${t.entry_ts?.slice(0, 16) || "—"} → ${t.exit_ts?.slice(11, 16) || "—"} · ${t.qty}주 · ${pct} · 순${formatWon(t.net_pnl_krw)} · ${t.sell_reason || ""}`;
    li.className = profitClass(t.net_pnl_krw);
    tradesList.appendChild(li);
  }
}

async function loadTradeStockChart(code, opts = {}) {
  const silent = opts.silent === true;
  selectedTradeCode = code;
  if (!silent) {
    $("trade-chart-loading").classList.remove("hidden");
    $("trade-chart-wrap").classList.add("hidden");
    $("trade-chart-trades").innerHTML = "";
  }

  document.querySelectorAll(".stock-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.code === code);
  });

  try {
    const data = await api(
      `/api/journal/trade-charts/${encodeURIComponent(code)}?days=90`
    );
    renderStockChart(data);
  } catch (ex) {
    if (!silent) {
      $("trade-chart-loading").classList.add("hidden");
      $("trade-chart-trades").innerHTML = `<li class="error">${ex.message}</li>`;
    }
  }
}

function renderTradeStockTabs(stocks) {
  tradedStocksCache = stocks || [];
  const tabs = $("trade-stock-tabs");
  const empty = $("trade-chart-empty");
  const count = $("trade-chart-count");
  tabs.innerHTML = "";
  count.textContent = String(tradedStocksCache.length);

  if (!tradedStocksCache.length) {
    empty.classList.remove("hidden");
    destroyStockChart();
    $("trade-chart-wrap").classList.add("hidden");
    $("trade-chart-loading").classList.add("hidden");
    return;
  }
  empty.classList.add("hidden");

  for (const s of tradedStocksCache) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "stock-tab";
    btn.dataset.code = s.code;
    const pnl =
      s.net_pnl_krw != null
        ? ` · ${s.net_pnl_krw >= 0 ? "+" : ""}${s.net_pnl_krw.toLocaleString()}`
        : "";
    btn.innerHTML = `${s.name}<span class="tab-code">${s.code}${pnl}</span>`;
    btn.addEventListener("click", () => loadTradeStockChart(s.code));
    tabs.appendChild(btn);
  }

  const pick =
    tradedStocksCache.find((s) => s.code === selectedTradeCode)?.code ||
    tradedStocksCache[0].code;
  loadTradeStockChart(pick);
}

async function loadTradedStocks() {
  try {
    const data = await api("/api/journal/traded-stocks?days=60&limit=12");
    renderTradeStockTabs(data.stocks || []);
  } catch (ex) {
    $("trade-chart-empty").textContent = ex.message;
    $("trade-chart-empty").classList.remove("hidden");
  }
}

function renderHoldings(holdings) {
  const list = $("holdings-list");
  const empty = $("holdings-empty");
  list.innerHTML = "";
  $("holdings-count").textContent = String(holdings.length);

  if (!holdings.length) {
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");

  for (const h of holdings) {
    const li = document.createElement("li");
    li.className = "holding-item";
    const tags = (h.tags || [])
      .map((t) => `<span class="tag">${t}</span>`)
      .join("");
    const hold =
      h.hold_minutes != null ? ` · ${Math.round(h.hold_minutes)}분` : "";
    li.innerHTML = `
      <header>
        <span class="name">${h.name} <span class="muted">(${h.code})</span></span>
        <span class="${profitClass(h.profit_pct)}">${h.profit_pct >= 0 ? "+" : ""}${h.profit_pct}%</span>
      </header>
      <p class="muted">${h.qty}주 · 매매가능 ${h.sellable_qty} · ${h.current_price.toLocaleString()}원${hold}</p>
      <p class="muted">고점 ${h.peak_profit_pct >= 0 ? "+" : ""}${h.peak_profit_pct}%</p>
      ${tags ? `<div class="tags">${tags}</div>` : ""}
    `;
    list.appendChild(li);
  }
}

function renderChart(holdings) {
  const canvas = $("profit-chart");
  const ctx = canvas.getContext("2d");
  const labels = holdings.map((h) => h.name);
  const values = holdings.map((h) => h.profit_pct);
  const colors = values.map((v) =>
    v >= 0 ? "rgba(61, 214, 140, 0.75)" : "rgba(240, 113, 120, 0.75)"
  );

  if (profitChart) profitChart.destroy();
  if (!holdings.length) {
    profitChart = null;
    return;
  }

  profitChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "수익률 %",
          data: values,
          backgroundColor: colors,
          borderRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: {
          ticks: { color: "#8b9cb3" },
          grid: { color: "#2d3a4d" },
        },
        x: {
          ticks: { color: "#8b9cb3", maxRotation: 45, minRotation: 0 },
          grid: { display: false },
        },
      },
    },
  });
}

function fmtPct(v) {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v}%`;
}

function renderStatsTable(tableId, rows) {
  const tbody = $(tableId).querySelector("tbody");
  tbody.innerHTML = "";
  if (!rows || !rows.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="4" class="muted">기록 없음</td>';
    tbody.appendChild(tr);
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.label}</td>
      <td>${row.count}</td>
      <td>${row.win_rate_pct != null ? `${row.win_rate_pct}%` : "—"}</td>
      <td class="${profitClass(row.avg_profit_pct)}">${fmtPct(row.avg_profit_pct)}</td>
    `;
    tbody.appendChild(tr);
  }
}

function renderJournalStats(stats) {
  const summary = $("stats-summary");
  const period = $("stats-period");
  const recent = $("stats-recent-list");

  if (!stats || !stats.summary || stats.summary.count === 0) {
    period.textContent = stats?.filter?.days ? `${stats.filter.days}일` : "—";
    summary.textContent = "완결 매도 기록 없음";
    summary.className = "status-line muted";
    renderStatsTable("stats-entry-table", []);
    renderStatsTable("stats-exit-table", []);
    recent.innerHTML = '<li class="muted">기록 없음</li>';
    return;
  }

  const flt = stats.filter || {};
  period.textContent = flt.days ? `최근 ${flt.days}일` : "전체";
  const s = stats.summary;
  summary.textContent = `완결 ${s.count}건 · 승 ${s.wins} / 패 ${s.losses} · 승률 ${s.win_rate_pct}% · 평균 ${fmtPct(s.avg_profit_pct)} · 합계 ${fmtPct(s.sum_profit_pct)}`;
  summary.className = `status-line ${profitClass(s.avg_profit_pct)}`;

  renderStatsTable("stats-entry-table", stats.by_entry || []);
  renderStatsTable("stats-exit-table", stats.by_exit_category || []);

  recent.innerHTML = "";
  for (const t of stats.recent_closed || []) {
    const li = document.createElement("li");
    li.innerHTML = `${t.ts} · ${t.name} <span class="${profitClass(t.profit_pct)}">${fmtPct(t.profit_pct)}</span> · ${t.entry_label} → ${t.exit_label}`;
    recent.appendChild(li);
  }
}

function renderTrades(trades) {
  const list = $("trades-list");
  list.innerHTML = "";
  if (!trades.length) {
    list.innerHTML = '<li class="muted">기록 없음</li>';
    return;
  }
  for (const t of trades) {
    const li = document.createElement("li");
    const pct =
      t.profit_pct != null
        ? ` <span class="${profitClass(t.profit_pct)}">(${t.profit_pct >= 0 ? "+" : ""}${t.profit_pct}%)</span>`
        : "";
    const qty = t.qty != null ? ` ${t.qty}주` : "";
    const price = t.price != null ? ` @ ${t.price.toLocaleString()}` : "";
    li.innerHTML = `${t.ts} · ${t.event} · ${t.name || t.code}${qty}${price}${pct}`;
    list.appendChild(li);
  }
}

function renderDashboard(data) {
  $("error-banner").classList.add("hidden");

  const mode = `${data.trade_mode_label} · ${data.strategy_label}`;
  const host = data.runtime_host ? ` · ${data.runtime_host}` : "";
  $("meta-line").textContent = `${mode} · ${data.market_status}${host}`;

  if (data.deposit) {
    $("cash-value").textContent = `${data.deposit.cash_fmt}원`;
    $("orderable-value").textContent = `${data.deposit.orderable_fmt}원`;
  } else {
    $("cash-value").textContent = "조회 실패";
    $("orderable-value").textContent = "—";
    $("error-banner").textContent = data.deposit_error || "예수금 조회 실패";
    $("error-banner").classList.remove("hidden");
  }

  $("portfolio-value").textContent = `${data.portfolio_value_fmt}원`;
  $("auto-value").textContent = data.auto_trading ? "ON" : "OFF";
  $("auto-value").className = data.auto_trading ? "profit-pos" : "muted";

  renderAccountSummary(
    data.account_summary,
    data.deposit,
    data.portfolio_value
  );
  window.__lastHoldings = data.holdings || [];
  renderHoldings(data.holdings || []);
  renderChart(data.holdings || []);

  const buy = data.buy_status || {};
  const pnl =
    buy.today_pnl_pct != null
      ? `오늘 손익(근사) ${buy.today_pnl_pct >= 0 ? "+" : ""}${buy.today_pnl_pct}% · `
      : "";
  $("buy-status-line").textContent = `${pnl}신규매수 ${buy.can_buy ? "가능" : "중지"}`;
  $("buy-status-line").className = `status-line ${buy.can_buy ? "profit-pos" : "profit-neg"}`;

  const reasons = $("block-reasons");
  reasons.innerHTML = "";
  for (const r of buy.block_reasons || []) {
    const li = document.createElement("li");
    li.textContent = r;
    reasons.appendChild(li);
  }

  renderNewsSessions(data);

  if (data.holdings_error) {
    $("error-banner").textContent = data.holdings_error;
    $("error-banner").classList.remove("hidden");
  }

  renderJournalStats(data.journal_stats);
  renderTrades(data.recent_trades || []);
  $("updated-at").textContent = `전체 갱신 ${data.updated_at}`;
  $("chart-updated-at").textContent = `차트 ${new Date().toLocaleTimeString("ko-KR")}`;

  const ext = $("external-url");
  if (data.external_url) {
    ext.href = data.external_url;
    ext.textContent = "외부 URL";
    ext.classList.remove("hidden");
  } else {
    ext.classList.add("hidden");
  }
}

async function refreshChartsOnly() {
  if (authBlocked || !getToken()) {
    stopChartAutoRefresh();
    return;
  }
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const data = await api("/api/dashboard");
    renderChart(data.holdings || []);
    if (data.account_summary) {
      renderMonthlyPnlChart(data.account_summary.by_month || []);
    }
    if (selectedTradeCode) {
      await loadTradeStockChart(selectedTradeCode, { silent: true });
    }
    $("chart-updated-at").textContent = `차트 ${new Date().toLocaleTimeString("ko-KR")}`;
  } catch {
    /* ignore background chart errors */
  } finally {
    refreshInFlight = false;
  }
}

function showCommandResult(text, ok = true) {
  const box = $("command-result");
  box.textContent = text;
  box.classList.remove("hidden", "command-error");
  if (!ok) box.classList.add("command-error");
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function hideCommandArgs() {
  pendingCommand = null;
  $("command-args-box").classList.add("hidden");
  $("command-arg-input").value = "";
}

function openCommandArgs(item) {
  pendingCommand = item;
  $("command-args-label").textContent = item.args_label || "인자";
  $("command-arg-input").placeholder = item.args_placeholder || "";
  let preset = "";
  if (item.id === "sell") {
    const h = (window.__lastHoldings || []).find((x) => (x.sellable_qty || 0) > 0);
    if (h) preset = `${h.code} ${h.sellable_qty}`;
  }
  $("command-arg-input").value = preset;
  $("command-args-box").classList.remove("hidden");
  $("command-args-box").scrollIntoView({ behavior: "smooth", block: "nearest" });
  $("command-arg-input").focus();
  $("command-arg-input").select();
}

async function executeCommandText(text, refreshAfter = false) {
  showCommandResult("실행 중…", true);
  try {
    const res = await api("/api/commands/run", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    showCommandResult(res.text || "(응답 없음)", res.ok !== false);
    if (refreshAfter || /\/auto|\/buy|\/sell|\/mode|\/capital|\/reset|\/trendbuy/i.test(text)) {
      await loadDashboard(true);
    }
  } catch (ex) {
    showCommandResult(ex.message, false);
  }
}

async function runCommandItem(item) {
  if (item.needs_args) {
    openCommandArgs(item);
    return;
  }
  await executeCommandText(item.cmd, true);
}

function renderCommandMenu(menu) {
  const root = $("command-groups");
  root.innerHTML = "";
  for (const group of menu.groups || []) {
    const section = document.createElement("div");
    section.className = "command-group";
    const title = document.createElement("h3");
    title.className = "stats-subhead";
    title.textContent = group.group;
    section.appendChild(title);
    const grid = document.createElement("div");
    grid.className = "command-grid";
    for (const item of group.items || []) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn ghost small command-btn";
      btn.textContent = item.label;
      btn.title = item.cmd + (item.args_placeholder ? ` ${item.args_placeholder}` : "");
      btn.addEventListener("click", () => runCommandItem(item));
      grid.appendChild(btn);
    }
    section.appendChild(grid);
    root.appendChild(section);
  }
}

async function loadCommandMenu() {
  try {
    const menu = await api("/api/commands/menu");
    renderCommandMenu(menu);
  } catch (ex) {
    $("command-groups").innerHTML = `<p class="error">${ex.message}</p>`;
  }
}

async function loadDashboard(fullRefresh = true) {
  const data = await api("/api/dashboard");
  renderDashboard(data);
  if (fullRefresh) {
    await loadTradedStocks();
    await loadCommandMenu();
  }
}

function startChartAutoRefresh() {
  stopChartAutoRefresh();
  chartRefreshTimer = setInterval(() => {
    refreshChartsOnly();
  }, CHART_REFRESH_MS);
}

function stopChartAutoRefresh() {
  if (chartRefreshTimer) clearInterval(chartRefreshTimer);
  chartRefreshTimer = null;
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("login-error");
  err.classList.add("hidden");
  try {
    const body = {
      username: $("username").value.trim(),
      password: $("password").value,
    };
    const res = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    });
    setToken(res.access_token);
    authBlocked = false;
    show("dashboard");
    await loadDashboard(true);
    startChartAutoRefresh();
  } catch (ex) {
    err.textContent = ex.message;
    err.classList.remove("hidden");
  }
});

$("command-args-run").addEventListener("click", () => {
  if (!pendingCommand) return;
  const args = $("command-arg-input").value.trim();
  if (pendingCommand.needs_args && !args) {
    showCommandResult(
      `인자를 입력하세요. 예: ${pendingCommand.args_placeholder || "005930 1"}`,
      false
    );
    $("command-arg-input").focus();
    return;
  }
  const text = args ? `${pendingCommand.cmd} ${args}` : pendingCommand.cmd;
  hideCommandArgs();
  executeCommandText(text, true);
});

$("command-args-cancel").addEventListener("click", hideCommandArgs);

$("command-arg-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("command-args-run").click();
  if (e.key === "Escape") hideCommandArgs();
});

$("logout-btn").addEventListener("click", () => {
  authBlocked = true;
  stopChartAutoRefresh();
  setToken(null);
  show("login");
});

$("refresh-btn").addEventListener("click", async () => {
  const btn = $("refresh-btn");
  btn.disabled = true;
  btn.textContent = "갱신 중…";
  $("error-banner").classList.add("hidden");
  try {
    await loadDashboard(true);
  } catch (ex) {
    $("error-banner").textContent = ex.message;
    $("error-banner").classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btn.textContent = "전체 새로고침";
  }
});

async function init() {
  if (getToken()) {
    try {
      show("dashboard");
      await loadDashboard(true);
      startChartAutoRefresh();
      return;
    } catch {
      setToken(null);
    }
  }
  show("login");
}

init();
