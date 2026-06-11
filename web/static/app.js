const TOKEN_KEY = "ai_stock_token";
const REFRESH_MS = 10000;

let profitChart = null;
let refreshTimer = null;

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
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) {
    setToken(null);
    show("login");
    throw new Error("로그인이 필요합니다.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `오류 (${res.status})`);
  }
  return data;
}

function formatWon(n) {
  if (n == null) return "—";
  return `${Number(n).toLocaleString("ko-KR")}원`;
}

function profitClass(pct) {
  if (pct > 0) return "profit-pos";
  if (pct < 0) return "profit-neg";
  return "";
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
  $("meta-line").textContent = `${mode} · ${data.market_status}`;

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

  if (data.holdings_error) {
    $("error-banner").textContent = data.holdings_error;
    $("error-banner").classList.remove("hidden");
  }

  renderJournalStats(data.journal_stats);
  renderTrades(data.recent_trades || []);
  $("updated-at").textContent = `갱신 ${data.updated_at}`;
}

async function loadDashboard() {
  const data = await api("/api/dashboard");
  renderDashboard(data);
}

function startAutoRefresh() {
  stopAutoRefresh();
  refreshTimer = setInterval(() => {
    loadDashboard().catch(() => {});
  }, REFRESH_MS);
}

function stopAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = null;
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
    show("dashboard");
    await loadDashboard();
    startAutoRefresh();
  } catch (ex) {
    err.textContent = ex.message;
    err.classList.remove("hidden");
  }
});

$("logout-btn").addEventListener("click", () => {
  stopAutoRefresh();
  setToken(null);
  show("login");
});

$("refresh-btn").addEventListener("click", () => {
  loadDashboard().catch((ex) => {
    $("error-banner").textContent = ex.message;
    $("error-banner").classList.remove("hidden");
  });
});

async function init() {
  if (getToken()) {
    try {
      show("dashboard");
      await loadDashboard();
      startAutoRefresh();
      return;
    } catch {
      setToken(null);
    }
  }
  show("login");
}

init();
