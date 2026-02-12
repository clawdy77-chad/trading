// === Navigation ===
let currentPage = 'dashboard';
const charts = {};
let refreshInterval = null;

// === Global Dashboard Filters ===
let dashFilters = {
  dateFrom: '',
  dateTo: '',
  direction: '',
  accountSize: 50000,
  displayMode: '$', // '$' or '%'
  quickFilter: 'all',
};

document.querySelectorAll('[data-page]').forEach(el => {
  el.addEventListener('click', e => {
    e.preventDefault();
    switchPage(el.dataset.page);
  });
});

function switchPage(page) {
  currentPage = page;
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-' + page).classList.add('active');
  document.querySelectorAll('[data-page]').forEach(a => {
    a.classList.toggle('active', a.dataset.page === page);
  });
  if (refreshInterval) { clearInterval(refreshInterval); refreshInterval = null; }
  loadPage(page);
}

function loadPage(page) {
  if (page === 'dashboard') loadDashboard();
  else if (page === 'trades') loadTrades();
  else if (page === 'analysis') loadAnalysis();
  else if (page === 'calendar') loadCalendar();
  else if (page === 'eval') loadEval();
  else if (page === 'chart') loadChartReplay();
}

// === Utils ===
function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }
function fmt(n) {
  const abs = Math.abs(n);
  const str = abs >= 1000 ? abs.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2}) : abs.toFixed(2);
  return n >= 0 ? `+$${str}` : `-$${str}`;
}
function fmtPct(n, acct) {
  const pct = (n / acct * 100);
  return (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
}
function fmtVal(n) {
  if (dashFilters.displayMode === '%') return fmtPct(n, dashFilters.accountSize);
  return fmt(n);
}
function fmtCompact(n) {
  const abs = Math.abs(n);
  if (abs >= 1000) return (n >= 0 ? '+' : '-') + '$' + (abs/1000).toFixed(1) + 'k';
  return fmt(n);
}
function fmtDollar(n) { return '$' + Math.abs(n).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2}); }
function pnlClass(n) { return n >= 0 ? 'green' : 'red'; }
// CSS: .green = bright white, .red = dim white
async function api(url) { const r = await fetch(url); return r.json(); }

// Chart defaults
Chart.defaults.color = 'rgba(139,148,158,0.6)';
Chart.defaults.borderColor = 'rgba(48,54,61,0.5)';
Chart.defaults.font.family = "'Inter', sans-serif";
Chart.defaults.font.size = 11;

function makeChart(canvasId, config) {
  if (charts[canvasId]) charts[canvasId].destroy();
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;
  charts[canvasId] = new Chart(ctx, config);
  return charts[canvasId];
}

function buildFilterQuery() {
  const p = new URLSearchParams();
  if (dashFilters.dateFrom) p.set('date_from', dashFilters.dateFrom);
  if (dashFilters.dateTo) p.set('date_to', dashFilters.dateTo);
  if (dashFilters.direction) p.set('direction', dashFilters.direction);
  return p.toString() ? '?' + p.toString() : '';
}

function setQuickFilter(key) {
  dashFilters.quickFilter = key;
  const now = new Date();
  const y = now.getFullYear();
  if (key === 'all') { dashFilters.dateFrom = ''; dashFilters.dateTo = ''; }
  else if (key === 'ytd') { dashFilters.dateFrom = `${y}-01-01`; dashFilters.dateTo = ''; }
  else if (key === '1y') { const d = new Date(now); d.setFullYear(y-1); dashFilters.dateFrom = d.toISOString().slice(0,10); dashFilters.dateTo = ''; }
  else if (key === '2y') { const d = new Date(now); d.setFullYear(y-2); dashFilters.dateFrom = d.toISOString().slice(0,10); dashFilters.dateTo = ''; }
  else if (key === '2024') { dashFilters.dateFrom = '2024-01-01'; dashFilters.dateTo = '2025-01-01'; }
  else if (key === '2025') { dashFilters.dateFrom = '2025-01-01'; dashFilters.dateTo = '2026-01-01'; }
  loadDashboard();
}

function setDirectionFilter(dir) {
  dashFilters.direction = dir;
  loadDashboard();
}

function setDisplayMode(mode) {
  dashFilters.displayMode = mode;
  loadDashboard();
}

function setAccountSize(val) {
  dashFilters.accountSize = parseFloat(val) || 50000;
  if (dashFilters.displayMode === '%') loadDashboard();
}

function applyDateFilter() {
  dashFilters.dateFrom = document.getElementById('filterDateFrom')?.value || '';
  dashFilters.dateTo = document.getElementById('filterDateTo')?.value || '';
  dashFilters.quickFilter = 'custom';
  loadDashboard();
}

// === Dashboard ===
let dashCalYear, dashCalMonth;
{ const now = new Date(); dashCalYear = now.getFullYear(); dashCalMonth = now.getMonth() + 1; }

async function loadBotStatus() {
  try {
    const b = await api('/api/bot/status');
    const el = document.getElementById('botStatusBar');
    if (!el) return;
    const running = b.running;
    const pos = b.position || b.positions || null;
    let posHtml = '';
    if (pos && typeof pos === 'object' && !Array.isArray(pos)) {
      posHtml = `<span class="bot-sep">|</span><span class="bot-label">Position:</span> <span class="bot-val">${pos.instrument || ''} ${pos.direction || ''} ${pos.units || ''}</span>`;
    } else if (Array.isArray(pos) && pos.length > 0) {
      posHtml = pos.map(p => `<span class="bot-sep">|</span><span class="bot-val">${p.instrument||''} ${p.direction||''}</span>`).join('');
    }
    el.innerHTML = `<div class="bot-dot ${running ? 'running' : 'stopped'}"></div>
      <span class="bot-val">${running ? 'Bot Running' : 'Bot Stopped'}</span>
      ${posHtml}
      ${b.last_signal ? `<span class="bot-sep">|</span><span class="bot-label">Last:</span> <span class="bot-val">${b.last_signal}</span>` : ''}`;
  } catch(e) {}
}

async function loadAccountBar() {
  try {
    const a = await api('/api/account');
    const el = document.getElementById('accountBar');
    if (!el) return;
    el.innerHTML = `
      <div class="acct-item"><span class="acct-label">Balance</span><span class="acct-val">${fmtDollar(a.balance)}</span></div>
      <div class="acct-item"><span class="acct-label">Equity</span><span class="acct-val">${fmtDollar(a.equity)}</span></div>
      <div class="acct-item"><span class="acct-label">Unrealized P&L</span><span class="acct-val ${pnlClass(a.unrealized_pnl)}">${fmt(a.unrealized_pnl)}</span></div>
      <div class="acct-item"><span class="acct-label">Open Trades</span><span class="acct-val">${a.open_trade_count}</span></div>
      <div class="acct-item"><span class="acct-label">Margin Used</span><span class="acct-val">${fmtDollar(a.margin_used)}</span></div>`;
  } catch(e) {
    const el = document.getElementById('accountBar');
    if (el) el.innerHTML = '<span style="color:var(--text3);font-size:.78em">Account unavailable</span>';
  }
}

async function loadSignalFeed() {
  try {
    const d = await api('/api/signals/recent');
    const el = document.getElementById('signalFeed');
    if (!el) return;
    if (!d.signals || d.signals.length === 0) {
      el.innerHTML = '<h2>Recent Signals</h2><div style="padding:10px 16px;color:var(--text3);font-size:.78em">No signals yet</div>';
      return;
    }
    el.innerHTML = '<h2>Recent Signals</h2>' + d.signals.slice(0, 8).map(s =>
      `<div class="signal-row">
        <span class="sig-time">${s.timestamp}</span>
        <span class="sig-inst">${s.instrument}</span>
        <span class="sig-dir">${s.direction}</span>
        <span class="sig-detail">${s.fractal} @ ${s.entry} SL=${s.sl} TP=${s.tp} R:R=${s.rr} [${s.killzone}]</span>
      </div>`
    ).join('');
  } catch(e) {}
}

async function loadDashboard() {
  const q = buildFilterQuery();
  const [s, dailyData] = await Promise.all([
    api('/api/stats/filtered' + q),
    api('/api/stats/daily'),
  ]);

  const qf = dashFilters.quickFilter;
  const df = dashFilters.direction;
  const dm = dashFilters.displayMode;
  const acctOptions = [25000, 50000, 100000, 150000, 200000];

  const filterBarHtml = `
    <div class="filter-bar">
      <label>Range</label>
      <input type="date" id="filterDateFrom" value="${dashFilters.dateFrom}" onchange="applyDateFilter()">
      <span style="color:var(--text3);font-size:.75em">→</span>
      <input type="date" id="filterDateTo" value="${dashFilters.dateTo}" onchange="applyDateFilter()">
      <div class="filter-sep"></div>
      ${['all','ytd','1y','2y','2024','2025'].map(k => {
        const labels = {all:'All',ytd:'YTD','1y':'1Y','2y':'2Y','2024':'2024','2025':'2025'};
        return `<button class="filter-btn ${qf===k?'active':''}" onclick="setQuickFilter('${k}')">${labels[k]}</button>`;
      }).join('')}
      <div class="filter-sep"></div>
      <label>Direction</label>
      ${['','long','short'].map(d => {
        const labels = {'':'All','long':'Long','short':'Short'};
        return `<button class="filter-btn ${df===d?'active':''}" onclick="setDirectionFilter('${d}')">${labels[d]}</button>`;
      }).join('')}
      <div class="filter-sep"></div>
      <label>Account</label>
      <select onchange="setAccountSize(this.value)">
        ${acctOptions.map(v => `<option value="${v}" ${dashFilters.accountSize===v?'selected':''}>${'$'+(v/1000)+'K'}</option>`).join('')}
      </select>
      <div class="display-toggle">
        <button class="${dm==='$'?'active':''}" onclick="setDisplayMode('$')">$</button>
        <button class="${dm==='%'?'active':''}" onclick="setDisplayMode('%')">%</button>
      </div>
    </div>`;

  if (!s.total) {
    $('#page-dashboard').innerHTML = `
      <h1>Dashboard</h1>
      ${filterBarHtml}
      <div id="botStatusBar" class="bot-status-bar"></div>
      <div id="accountBar" class="account-bar"></div>
      <p style="color:var(--text2);padding:20px 0">No trades for this filter.</p>`;
    loadBotStatus(); loadAccountBar();
    refreshInterval = setInterval(() => { loadBotStatus(); loadAccountBar(); }, 30000);
    return;
  }

  // Downsample for charts
  let eqData = s.equity_curve, eqLabels = s.equity_labels, rollingWr = s.rolling_wr;
  const maxPts = 500;
  if (eqData.length > maxPts) {
    const step = Math.ceil(eqData.length / maxPts);
    eqData = eqData.filter((_,i) => i % step === 0 || i === s.equity_curve.length-1);
    eqLabels = eqLabels.filter((_,i) => i % step === 0 || i === s.equity_labels.length-1);
    rollingWr = rollingWr.filter((_,i) => i % step === 0 || i === s.rolling_wr.length-1);
  }

  const pVal = s.p_value;
  const pSig = pVal < 0.01 ? 'Highly Significant' : pVal < 0.05 ? 'Significant' : pVal < 0.1 ? 'Marginal' : 'Not Significant';
  const pColor = pVal < 0.05 ? 'green' : pVal < 0.1 ? 'cyan' : 'red';

  $('#page-dashboard').innerHTML = `
    <h1>Dashboard</h1>

    ${filterBarHtml}

    <div id="botStatusBar" class="bot-status-bar"><div class="bot-dot stopped"></div><span class="bot-val">Loading...</span></div>
    <div id="accountBar" class="account-bar"><span style="color:var(--text3);font-size:.78em">Loading account...</span></div>

    <div class="strategy-card">
      <div class="strat-name">V24 Optimized</div>
      <div class="strat-divider"></div>
      <div class="strat-stat"><span class="strat-label">Win Rate</span><span class="strat-val">${s.win_rate}%</span></div>
      <div class="strat-divider"></div>
      <div class="strat-stat"><span class="strat-label">Profit Factor</span><span class="strat-val">${s.profit_factor}</span></div>
      <div class="strat-divider"></div>
      <div class="strat-stat"><span class="strat-label">SQN</span><span class="strat-val">${s.sqn}</span></div>
      <div class="strat-divider"></div>
      <div class="strat-stat"><span class="strat-label">Trades</span><span class="strat-val">${s.total}</span></div>
    </div>

    <!-- Row 1: Core Performance -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="label">Net Profit</div>
        <div class="value ${pnlClass(s.net_profit)}">${fmtVal(s.net_profit)}</div>
        <div class="sub">Peak: ${fmtVal(s.peak_equity)}</div>
      </div>
      <div class="stat-card">
        <div class="label">Total Trades</div>
        <div class="value cyan">${s.total.toLocaleString()}</div>
        <div class="sub">${s.wins}W / ${s.losses}L</div>
      </div>
      <div class="stat-card">
        <div class="label">Win Rate</div>
        <div class="value">${s.win_rate}%</div>
        <div class="sub">Avg W: $${s.avg_win.toFixed(0)} / L: $${s.avg_loss.toFixed(0)}</div>
      </div>
      <div class="stat-card">
        <div class="label">Profit Factor</div>
        <div class="value ${s.profit_factor >= 1.5 ? 'green' : s.profit_factor >= 1 ? '' : 'red'}">${s.profit_factor}</div>
        <div class="sub">${s.current_streak} ${s.streak_type} streak</div>
      </div>
    </div>

    <!-- Row 2: Risk Metrics -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="label">Sharpe Ratio</div>
        <div class="value ${s.sharpe >= 1 ? 'green' : s.sharpe >= 0 ? 'cyan' : 'red'}">${s.sharpe.toFixed(2)}</div>
        <div class="sub">Annualized</div>
      </div>
      <div class="stat-card">
        <div class="label">Max Drawdown</div>
        <div class="value red">${dashFilters.displayMode === '%' ? fmtPct(-s.max_drawdown, dashFilters.accountSize) : '-$' + s.max_drawdown.toLocaleString('en-US',{minimumFractionDigits:2})}</div>
        <div class="sub">From peak</div>
      </div>
      <div class="stat-card">
        <div class="label">Recovery Factor</div>
        <div class="value ${s.recovery_factor >= 2 ? 'green' : 'cyan'}">${s.recovery_factor.toFixed(2)}</div>
        <div class="sub">Net P&L / Max DD</div>
      </div>
      <div class="stat-card">
        <div class="label">SQN</div>
        <div class="value ${s.sqn >= 2 ? 'green' : s.sqn >= 1 ? 'cyan' : 'red'}">${s.sqn.toFixed(2)}</div>
        <div class="sub">√n × avg / σ</div>
      </div>
    </div>

    <!-- Row 3: Additional -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="label">Stagnation</div>
        <div class="value cyan">${s.stagnation_days}</div>
        <div class="sub">Max days w/o new high</div>
      </div>
      <div class="stat-card">
        <div class="label">P-Value</div>
        <div class="value ${pColor}">${s.p_value < 0.001 ? '<0.001' : s.p_value.toFixed(4)}</div>
        <div class="sub">${pSig}</div>
      </div>
      <div class="stat-card">
        <div class="label">Trading Days</div>
        <div class="value cyan">${s.trading_days.toLocaleString()}</div>
        <div class="sub">Unique days</div>
      </div>
      <div class="stat-card">
        <div class="label">Avg Trade</div>
        <div class="value ${pnlClass(s.avg_trade)}">${fmtVal(s.avg_trade)}</div>
        <div class="sub">Expectancy</div>
      </div>
    </div>

    <div id="signalFeed" class="signal-feed"><h2>Recent Signals</h2><div style="padding:10px 16px;color:var(--text3);font-size:.78em">Loading...</div></div>

    <div class="section">
      <div class="chart-box">
        <h2>Equity Curve</h2>
        <canvas id="equityChart" height="80"></canvas>
      </div>
    </div>

    <div class="section">
      <div class="chart-box">
        <h2>Daily P&L</h2>
        <canvas id="dailyPnlChart" height="55"></canvas>
      </div>
    </div>

    <div class="dash-grid">
      <div class="chart-box">
        <div class="cal-nav">
          <button onclick="dashCalMonth--;if(dashCalMonth<1){dashCalMonth=12;dashCalYear--;}renderDashCal()">‹</button>
          <span class="cal-title" id="dashCalTitle"></span>
          <button onclick="dashCalMonth++;if(dashCalMonth>12){dashCalMonth=1;dashCalYear++;}renderDashCal()">›</button>
        </div>
        <div id="dashCalGrid"></div>
      </div>
      <div class="weekly-sidebar">
        <h2>Weekly P&L</h2>
        <div id="weeklyBreakdown"></div>
      </div>
    </div>

    <div class="chart-row">
      <div class="chart-box">
        <h2>Rolling 20-Trade Win Rate</h2>
        <canvas id="rollingWrChart" height="100"></canvas>
      </div>
      <div class="chart-box">
        <h2>Win / Loss</h2>
        <canvas id="winLossChart" height="100"></canvas>
      </div>
    </div>`;

  // Async widgets
  loadBotStatus();
  loadAccountBar();
  loadSignalFeed();
  renderDashCal();
  refreshInterval = setInterval(() => { loadBotStatus(); loadAccountBar(); }, 30000);

  // Equity chart with gradient
  const eqCanvas = document.getElementById('equityChart');
  const eqCtx = eqCanvas.getContext('2d');
  const gradient = eqCtx.createLinearGradient(0, 0, 0, eqCanvas.parentElement.clientHeight || 300);
  gradient.addColorStop(0, 'rgba(34, 197, 94, 0.12)');
  gradient.addColorStop(1, 'rgba(34, 197, 94, 0.0)');

  makeChart('equityChart', {
    type: 'line',
    data: { labels: eqLabels, datasets: [{
      data: eqData,
      borderColor: 'rgba(255,255,255,0.85)',
      backgroundColor: gradient,
      fill: true, pointRadius: 0, borderWidth: 1.5, tension: 0.3
    }]},
    options: { responsive:true, plugins:{legend:{display:false}}, scales:{
      x:{display:false}, y:{grid:{color:'rgba(48,54,61,0.4)'},ticks:{callback:v=>'$'+v.toLocaleString()}}
    }, interaction: { intersect: false, mode: 'index' }}
  });

  // Daily P&L bar chart
  if (dailyData.daily && dailyData.daily.length > 0) {
    let dp = dailyData.daily;
    // Apply date filter to daily data too
    if (dashFilters.dateFrom) dp = dp.filter(d => d.date >= dashFilters.dateFrom);
    if (dashFilters.dateTo) dp = dp.filter(d => d.date < dashFilters.dateTo);
    if (dp.length > 0) {
      const dpLabels = dp.map(d => d.date);
      const dpData = dp.map(d => d.pnl);
      const dpColors = dpData.map(v => v >= 0 ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.5)');
      makeChart('dailyPnlChart', {
        type: 'bar',
        data: { labels: dpLabels, datasets: [{
          data: dpData, backgroundColor: dpColors, borderRadius: 2
        }]},
        options: { responsive:true, plugins:{legend:{display:false}}, scales:{
          x:{display:false}, y:{grid:{color:'rgba(48,54,61,0.4)'},ticks:{callback:v=>'$'+v.toLocaleString()}}
        }}
      });
    }
  }

  // Rolling WR
  makeChart('rollingWrChart', {
    type: 'line',
    data: { labels: eqLabels, datasets: [{
      data: rollingWr,
      borderColor: 'rgba(255,255,255,0.6)',
      pointRadius: 0, borderWidth: 1.5, tension: 0.3
    },{
      data: Array(rollingWr.length).fill(50),
      borderColor: 'rgba(139,148,158,0.2)',
      borderDash:[5,5], pointRadius:0, borderWidth:1
    }]},
    options: { responsive:true, plugins:{legend:{display:false}}, scales:{
      x:{display:false}, y:{min:0,max:100,grid:{color:'rgba(48,54,61,0.4)'},ticks:{callback:v=>v+'%'}}
    }}
  });

  // Win/Loss donut
  makeChart('winLossChart', {
    type: 'doughnut',
    data: { labels:['Wins','Losses'], datasets:[{
      data:[s.wins, s.losses],
      backgroundColor:['rgba(255,255,255,0.85)','rgba(255,255,255,0.3)'],
      borderWidth:0, borderColor:'#161b22'
    }]},
    options: { responsive:true, cutout:'72%', plugins:{legend:{position:'bottom',labels:{padding:14,usePointStyle:true,pointStyle:'circle',color:'#8b949e'}}}}
  });
}

async function renderDashCal() {
  const months = ['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const data = await api(`/api/calendar/${dashCalYear}/${dashCalMonth}`);

  const titleEl = document.getElementById('dashCalTitle');
  if (titleEl) titleEl.textContent = `${months[dashCalMonth]} ${dashCalYear}`;

  const firstDay = new Date(dashCalYear, dashCalMonth-1, 1).getDay();
  const daysInMonth = new Date(dashCalYear, dashCalMonth, 0).getDate();
  const startIdx = firstDay === 0 ? 6 : firstDay - 1;

  let cells = '';
  const headers = ['M','T','W','T','F','S','S'];
  headers.forEach(h => cells += `<div class="mini-cal-header">${h}</div>`);

  for (let i = 0; i < startIdx; i++) cells += '<div class="mini-cal-cell empty"></div>';

  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${dashCalYear}-${String(dashCalMonth).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    const dayData = data.days[dateStr];
    const cls = dayData ? (dayData.pnl >= 0 ? 'positive' : 'negative') : '';
    cells += `<div class="mini-cal-cell ${cls}" onclick="showDayTrades('${dateStr}')">
      <div class="day-num">${d}</div>
      ${dayData ? `<div class="day-pnl">${fmtCompact(dayData.pnl)}</div>` : ''}
    </div>`;
  }

  const grid = document.getElementById('dashCalGrid');
  if (grid) grid.innerHTML = `<div class="mini-cal-grid">${cells}</div>`;

  // Weekly breakdown
  const weeks = {};
  Object.entries(data.days).forEach(([dateStr, d]) => {
    const dt = new Date(dateStr);
    const weekStart = new Date(dt);
    weekStart.setDate(dt.getDate() - ((dt.getDay() + 6) % 7));
    const wk = weekStart.toISOString().slice(0,10);
    weeks[wk] = (weeks[wk] || 0) + d.pnl;
  });

  const wbEl = document.getElementById('weeklyBreakdown');
  if (wbEl) {
    const sorted = Object.entries(weeks).sort((a,b) => a[0].localeCompare(b[0]));
    wbEl.innerHTML = sorted.map(([wk, pnl]) => {
      const d = new Date(wk);
      const label = `${d.toLocaleDateString('en-US', {month:'short', day:'numeric'})}`;
      return `<div class="week-row">
        <span class="week-label">Wk of ${label}</span>
        <span class="week-pnl ${pnlClass(pnl)}">${fmt(pnl)}</span>
      </div>`;
    }).join('');
  }
}

// === Trade Log ===
let tradePage = 1;
let tradeFilter = { instrument: '', outcome: '' };

async function loadTrades() {
  const d = await api(`/api/trades?page=${tradePage}&limit=50&instrument=${tradeFilter.instrument}&outcome=${tradeFilter.outcome}`);

  $('#page-trades').innerHTML = `
    <h1>Trade Log</h1>
    <div class="toolbar">
      <button class="btn btn-primary" onclick="showAddTrade()">+ Add Trade</button>
      <button class="btn btn-secondary" onclick="showImport()">Import CSV</button>
      <select onchange="tradeFilter.instrument=this.value;tradePage=1;loadTrades()">
        <option value="">All Instruments</option>
        <option value="NQ" ${tradeFilter.instrument==='NQ'?'selected':''}>NQ</option>
        <option value="ES" ${tradeFilter.instrument==='ES'?'selected':''}>ES</option>
        <option value="YM" ${tradeFilter.instrument==='YM'?'selected':''}>YM</option>
      </select>
      <select onchange="tradeFilter.outcome=this.value;tradePage=1;loadTrades()">
        <option value="">All Outcomes</option>
        <option value="win" ${tradeFilter.outcome==='win'?'selected':''}>Wins</option>
        <option value="loss" ${tradeFilter.outcome==='loss'?'selected':''}>Losses</option>
      </select>
      <span style="color:var(--text3);font-size:.78em;margin-left:auto">${d.total.toLocaleString()} trades</span>
    </div>
    <div class="table-wrap">
    <div style="overflow-x:auto">
    <table>
      <thead><tr>
        <th>Date</th><th>Instrument</th><th>Direction</th><th>Fractal</th><th>Killzone</th><th>Entry</th><th>Exit</th><th>TP Type</th><th>Outcome</th><th>P&L</th><th>Notes</th>
      </tr></thead>
      <tbody>${d.trades.map(t => `<tr class="clickable-row" onclick="showNoteModal(${t.id}, ${JSON.stringify((t.notes||'').replace(/"/g,'&quot;')).replace(/"/g,'&quot;')})">
        <td>${t.entry_time.slice(0,16).replace('T',' ')}</td>
        <td style="font-weight:600">${t.instrument}</td>
        <td style="text-transform:capitalize">${t.direction}</td>
        <td style="color:var(--text2)">${t.fractal}</td>
        <td style="color:var(--text2)">${t.killzone}</td>
        <td>${t.entry_price}</td>
        <td>${t.exit_price||'—'}</td>
        <td style="color:var(--text2)">${t.tp_type}</td>
        <td><span class="badge ${t.outcome}">${t.outcome}</span></td>
        <td style="font-weight:700" class="${pnlClass(t.pnl_dollar)}">${fmt(t.pnl_dollar)}</td>
        <td style="color:var(--text3);max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${t.notes ? '📝' : '—'}</td>
      </tr>`).join('')}</tbody>
    </table>
    </div></div>
    <div class="pagination">
      <button ${tradePage<=1?'disabled':''} onclick="tradePage--;loadTrades()">← Prev</button>
      <span style="color:var(--text3);font-size:.78em">${d.page} / ${d.pages}</span>
      <button ${tradePage>=d.pages?'disabled':''} onclick="tradePage++;loadTrades()">Next →</button>
    </div>`;
}

function showNoteModal(tradeId, currentNote) {
  const m = $('#modal-content');
  const note = currentNote || '';
  m.innerHTML = `
    <h2>Trade Notes — #${tradeId}</h2>
    <textarea class="note-textarea" id="noteText">${note}</textarea>
    <div style="display:flex;gap:8px;margin-top:12px">
      <button class="btn btn-primary" onclick="saveNote(${tradeId})">Save Note</button>
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
    </div>`;
  $('#modal-overlay').classList.remove('hidden');
}

async function saveNote(tradeId) {
  const text = document.getElementById('noteText').value;
  await fetch(`/api/trade/${tradeId}/note`, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ note: text })
  });
  closeModal();
  loadTrades();
}

function showAddTrade() {
  const m = $('#modal-content');
  m.innerHTML = `
    <h2>Add Trade</h2>
    <form id="addTradeForm" class="form-grid">
      <div><label>Instrument</label><select name="instrument"><option>NQ</option><option>ES</option><option>YM</option></select></div>
      <div><label>Direction</label><select name="direction"><option>long</option><option>short</option></select></div>
      <div><label>Entry Time</label><input type="datetime-local" name="entry_time" required></div>
      <div><label>Exit Time</label><input type="datetime-local" name="exit_time"></div>
      <div><label>Entry Price</label><input type="number" step="0.01" name="entry_price" required></div>
      <div><label>Exit Price</label><input type="number" step="0.01" name="exit_price"></div>
      <div><label>SL Price</label><input type="number" step="0.01" name="sl_price"></div>
      <div><label>TP Price</label><input type="number" step="0.01" name="tp_price"></div>
      <div><label>Fractal</label><select name="fractal"><option value="">—</option><option>F1_M30</option><option>F2_H1</option><option>F3_H4</option><option>F4_D1</option></select></div>
      <div><label>Killzone</label><select name="killzone"><option value="">—</option><option>London</option><option>NY</option></select></div>
      <div><label>TP Type</label><select name="tp_type"><option value="">—</option><option>swing_high</option><option>swing_low</option><option>unfilled_fvg</option><option>session_high</option><option>session_low</option></select></div>
      <div><label>Outcome</label><select name="outcome"><option>win</option><option>loss</option></select></div>
      <div><label>P&L ($)</label><input type="number" step="0.01" name="pnl_dollar"></div>
      <div><label>Risk ($)</label><input type="number" step="0.01" name="risk_amount" value="200"></div>
      <div class="full"><label>Notes</label><textarea name="notes" rows="2"></textarea></div>
      <div class="full" style="display:flex;gap:8px;margin-top:6px">
        <button type="submit" class="btn btn-primary">Save Trade</button>
        <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      </div>
    </form>`;
  $('#modal-overlay').classList.remove('hidden');

  document.getElementById('addTradeForm').onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const data = Object.fromEntries(fd);
    ['entry_price','exit_price','sl_price','tp_price','pnl_dollar','risk_amount'].forEach(k => data[k] = parseFloat(data[k])||0);
    await fetch('/api/trades', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) });
    closeModal();
    loadTrades();
  };
}

function showImport() {
  const m = $('#modal-content');
  m.innerHTML = `
    <h2>Import CSV</h2>
    <p style="color:var(--text2);margin-bottom:16px;font-size:.82em">Upload a CSV with columns: instrument, fractal, killzone, direction, entry_time, exit_time, entry_price, sl_price, tp_price, tp_type, sl_dist, rr_target, outcome, pnl_dollar, pnl_pts, conviction</p>
    <form id="importForm">
      <input type="file" accept=".csv" name="file" required style="margin-bottom:16px">
      <div style="display:flex;gap:8px">
        <button type="submit" class="btn btn-primary">Import</button>
        <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      </div>
    </form>`;
  $('#modal-overlay').classList.remove('hidden');

  document.getElementById('importForm').onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const r = await fetch('/api/import', { method:'POST', body:fd });
    const d = await r.json();
    alert(`Imported ${d.imported} trades`);
    closeModal();
    loadTrades();
  };
}

function closeModal() { $('#modal-overlay').classList.add('hidden'); }
$('#modal-overlay').addEventListener('click', e => { if (e.target === $('#modal-overlay')) closeModal(); });

// === Analysis ===
let analysisDim = 'instrument';
const analysisDims = [
  { key:'instrument', label:'Instrument' },
  { key:'fractal', label:'Fractal' },
  { key:'killzone', label:'Killzone' },
  { key:'day_of_week', label:'Day' },
  { key:'hour', label:'Hour' },
  { key:'tp_type', label:'TP Type' },
  { key:'direction', label:'Direction' },
];

async function loadAnalysis() {
  const [data, hm, bw, hourlyWr, fractalData, edgeDecay] = await Promise.all([
    api(`/api/analysis/${analysisDim}`),
    api('/api/heatmap'),
    api('/api/best_worst_days'),
    api('/api/analysis/hourly_wr'),
    api('/api/analysis/fractal'),
    api('/api/analysis/edge_decay'),
  ]);
  const groups = data.groups;

  $('#page-analysis').innerHTML = `
    <h1>Analysis</h1>
    <div class="tabs">${analysisDims.map(d =>
      `<div class="tab ${d.key===analysisDim?'active':''}" onclick="analysisDim='${d.key}';loadAnalysis()">${d.label}</div>`
    ).join('')}</div>

    <div class="chart-row">
      <div class="chart-box"><h2>P&L by ${analysisDim.replace('_',' ')}</h2><canvas id="analysisPnl"></canvas></div>
      <div class="chart-box"><h2>Win Rate by ${analysisDim.replace('_',' ')}</h2><canvas id="analysisWr"></canvas></div>
    </div>

    <div class="section">
      <div class="table-wrap">
      <table>
        <thead><tr><th>Name</th><th>Trades</th><th>Wins</th><th>Losses</th><th>Win Rate</th><th>P&L</th><th>PF</th><th>Avg P&L</th></tr></thead>
        <tbody>${groups.map(g => `<tr>
          <td style="font-weight:700">${g.name}</td><td>${g.total}</td><td class="win">${g.wins}</td><td class="loss">${g.losses}</td>
          <td>${g.win_rate}%</td><td class="${pnlClass(g.pnl)}" style="font-weight:700">${fmt(g.pnl)}</td><td>${g.profit_factor}</td><td class="${pnlClass(g.avg_pnl)}">${fmt(g.avg_pnl)}</td>
        </tr>`).join('')}</tbody>
      </table>
      </div>
    </div>

    <div class="section">
      <div class="chart-box">
        <h2>Hourly Win Rate</h2>
        <canvas id="hourlyWrChart" height="60"></canvas>
      </div>
    </div>

    <div class="section">
      <div class="chart-box">
        <h2>Per-Fractal Breakdown</h2>
        <canvas id="fractalChart" height="80"></canvas>
      </div>
      <div class="table-wrap" style="margin-top:12px">
        <table>
          <thead><tr><th>Fractal</th><th>Trades</th><th>Win Rate</th><th>P&L</th><th>PF</th><th>Avg P&L</th></tr></thead>
          <tbody>${fractalData.groups.map(g => `<tr>
            <td style="font-weight:700">${g.name}</td><td>${g.total}</td>
            <td>${g.win_rate}%</td><td class="${pnlClass(g.pnl)}" style="font-weight:700">${fmt(g.pnl)}</td>
            <td>${g.profit_factor}</td><td class="${pnlClass(g.avg_pnl)}">${fmt(g.avg_pnl)}</td>
          </tr>`).join('')}</tbody>
        </table>
      </div>
    </div>

    ${edgeDecay.rolling.length > 0 ? `
    <div class="section">
      <div class="chart-box">
        <h2>Edge Decay — Rolling 50-Trade Win Rate</h2>
        <canvas id="edgeDecayChart" height="80"></canvas>
      </div>
    </div>` : ''}

    <div class="section">
      <div class="chart-box">
        <h2>Trade Heatmap — Day × Hour (P&L)</h2>
        <div id="heatmapContainer"></div>
      </div>
    </div>

    <div class="chart-row">
      <div class="chart-box">
        <h2>Best Days</h2>
        <table><thead><tr><th>Date</th><th>P&L</th></tr></thead>
        <tbody>${bw.best.map(d=>`<tr><td>${d.date}</td><td class="green" style="font-weight:700">${fmt(d.pnl)}</td></tr>`).join('')}</tbody></table>
      </div>
      <div class="chart-box">
        <h2>Worst Days</h2>
        <table><thead><tr><th>Date</th><th>P&L</th></tr></thead>
        <tbody>${bw.worst.map(d=>`<tr><td>${d.date}</td><td class="red" style="font-weight:700">${fmt(d.pnl)}</td></tr>`).join('')}</tbody></table>
      </div>
    </div>`;

  const barColors = groups.map(g => g.pnl >= 0 ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.5)');
  makeChart('analysisPnl', {
    type:'bar',
    data:{ labels:groups.map(g=>g.name), datasets:[{ data:groups.map(g=>g.pnl), backgroundColor:barColors, borderRadius:3 }]},
    options:{ responsive:true, plugins:{legend:{display:false}}, scales:{
      x:{grid:{display:false}}, y:{grid:{color:'rgba(48,54,61,0.4)'},ticks:{callback:v=>'$'+v.toLocaleString()}}
    }}
  });

  makeChart('analysisWr', {
    type:'bar',
    data:{ labels:groups.map(g=>g.name), datasets:[{ data:groups.map(g=>g.win_rate), backgroundColor:'rgba(255,255,255,0.3)', borderRadius:3 }]},
    options:{ responsive:true, plugins:{legend:{display:false}}, scales:{
      x:{grid:{display:false}}, y:{min:0,max:100,grid:{color:'rgba(48,54,61,0.4)'},ticks:{callback:v=>v+'%'}}
    }}
  });

  const hrLabels = hourlyWr.hours.map(h => h.hour + ':00');
  const hrData = hourlyWr.hours.map(h => h.win_rate);
  const hrColors = hourlyWr.hours.map(h => h.win_rate >= 50 ? 'rgba(255,255,255,0.45)' : 'rgba(255,255,255,0.35)');
  makeChart('hourlyWrChart', {
    type:'bar',
    data:{ labels:hrLabels, datasets:[{ data:hrData, backgroundColor:hrColors, borderRadius:2 }]},
    options:{ responsive:true, plugins:{legend:{display:false},tooltip:{callbacks:{
      label: (ctx) => { const h = hourlyWr.hours[ctx.dataIndex]; return `WR: ${h.win_rate}% (${h.wins}/${h.total})`; }
    }}}, scales:{
      x:{grid:{display:false}}, y:{min:0,max:100,grid:{color:'rgba(48,54,61,0.4)'},ticks:{callback:v=>v+'%'}}
    }}
  });

  const fLabels = fractalData.groups.map(g => g.name);
  const fPnl = fractalData.groups.map(g => g.pnl);
  const fColors = fractalData.groups.map(g => g.pnl >= 0 ? 'rgba(255,255,255,0.5)' : 'rgba(255,255,255,0.5)');
  makeChart('fractalChart', {
    type:'bar',
    data:{ labels:fLabels, datasets:[{ label:'P&L', data:fPnl, backgroundColor:fColors, borderRadius:3 }]},
    options:{ responsive:true, plugins:{legend:{display:false}}, scales:{
      x:{grid:{display:false}}, y:{grid:{color:'rgba(48,54,61,0.4)'},ticks:{callback:v=>'$'+v.toLocaleString()}}
    }}
  });

  if (edgeDecay.rolling.length > 0) {
    const edLabels = edgeDecay.rolling.map((_,i) => i + 50);
    makeChart('edgeDecayChart', {
      type:'line',
      data:{ labels:edLabels, datasets:[{
        data:edgeDecay.rolling,
        borderColor:'rgba(255,255,255,0.5)',
        pointRadius:0, borderWidth:1.5, tension:0.3
      },{
        data:Array(edgeDecay.rolling.length).fill(edgeDecay.overall_wr),
        borderColor:'rgba(139,148,158,0.2)',
        borderDash:[5,5], pointRadius:0, borderWidth:1
      },{
        data:Array(edgeDecay.rolling.length).fill(50),
        borderColor:'rgba(255,255,255,0.15)',
        borderDash:[3,3], pointRadius:0, borderWidth:1
      }]},
      options:{ responsive:true, plugins:{legend:{display:false}}, scales:{
        x:{display:false}, y:{min:0,max:100,grid:{color:'rgba(48,54,61,0.4)'},ticks:{callback:v=>v+'%'}}
      }}
    });
  }

  // Heatmap
  const days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const container = document.getElementById('heatmapContainer');
  let hmHtml = '<div class="heatmap"><div class="heatmap-label"></div>';
  for (let h=0;h<24;h++) hmHtml += `<div class="heatmap-header">${h}</div>`;

  let maxVal = 0;
  hm.pnl.forEach(row => row.forEach(v => { if(Math.abs(v)>maxVal) maxVal=Math.abs(v); }));

  for (let d=0;d<7;d++) {
    hmHtml += `<div class="heatmap-label">${days[d]}</div>`;
    for (let h=0;h<24;h++) {
      const v = hm.pnl[d][h];
      const c = hm.counts[d][h];
      const intensity = maxVal ? Math.min(Math.abs(v)/maxVal, 1) : 0;
      const bg = v >= 0
        ? `rgba(255,255,255,${intensity*0.45})`
        : `rgba(255,255,255,${intensity*0.4})`;
      hmHtml += `<div class="heatmap-cell" style="background:${bg}" title="${days[d]} ${h}:00 | ${c} trades | $${v.toFixed(0)}">${c||''}</div>`;
    }
  }
  hmHtml += '</div>';
  container.innerHTML = hmHtml;
}

// === Calendar ===
let calYear, calMonth;
{ const now = new Date(); calYear = now.getFullYear(); calMonth = now.getMonth() + 1; }

async function loadCalendar() {
  const data = await api(`/api/calendar/${calYear}/${calMonth}`);
  const months = ['','January','February','March','April','May','June','July','August','September','October','November','December'];

  const firstDay = new Date(calYear, calMonth-1, 1).getDay();
  const daysInMonth = new Date(calYear, calMonth, 0).getDate();
  const startIdx = firstDay === 0 ? 6 : firstDay - 1;

  let cells = '';
  for (let i=0;i<startIdx;i++) cells += '<div class="cal-cell empty"></div>';

  for (let d=1;d<=daysInMonth;d++) {
    const dateStr = `${calYear}-${String(calMonth).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    const dayData = data.days[dateStr];
    const cls = dayData ? (dayData.pnl >= 0 ? 'positive' : 'negative') : '';
    cells += `<div class="cal-cell ${cls}" onclick="showDayTrades('${dateStr}')">
      <div class="day">${d}</div>
      ${dayData ? `<div class="pnl ${pnlClass(dayData.pnl)}">${fmt(dayData.pnl)}</div><div class="meta">${dayData.trades} trades · ${dayData.wins} wins</div>` : ''}
    </div>`;
  }

  let monthPnl = 0, monthTrades = 0, monthWins = 0;
  Object.values(data.days).forEach(d => { monthPnl += d.pnl; monthTrades += d.trades; monthWins += d.wins; });

  $('#page-calendar').innerHTML = `
    <h1>Calendar</h1>
    <div class="cal-nav">
      <button onclick="calMonth--;if(calMonth<1){calMonth=12;calYear--;}loadCalendar()">‹ Prev</button>
      <span class="cal-title">${months[calMonth]} ${calYear}</span>
      <button onclick="calMonth++;if(calMonth>12){calMonth=1;calYear++;}loadCalendar()">Next ›</button>
      <span style="margin-left:auto;color:var(--text2);font-size:.82em">
        ${monthTrades} trades · ${monthWins} wins · <span class="${pnlClass(monthPnl)}" style="font-weight:700">${fmt(monthPnl)}</span>
      </span>
    </div>
    <div class="cal-grid">
      <div class="cal-header">Mon</div><div class="cal-header">Tue</div><div class="cal-header">Wed</div>
      <div class="cal-header">Thu</div><div class="cal-header">Fri</div><div class="cal-header">Sat</div><div class="cal-header">Sun</div>
      ${cells}
    </div>`;
}

async function showDayTrades(day) {
  const d = await api(`/api/calendar/day/${day}`);
  if (!d.trades.length) return;
  const m = $('#modal-content');
  let totalPnl = d.trades.reduce((s,t) => s + t.pnl_dollar, 0);
  m.innerHTML = `
    <h2>${day} — <span class="${pnlClass(totalPnl)}">${fmt(totalPnl)}</span></h2>
    <div class="table-wrap">
    <table>
      <thead><tr><th>Time</th><th>Instrument</th><th>Direction</th><th>Fractal</th><th>Outcome</th><th>P&L</th></tr></thead>
      <tbody>${d.trades.map(t => `<tr>
        <td>${t.entry_time.slice(11,16)}</td><td>${t.instrument}</td><td>${t.direction}</td>
        <td>${t.fractal}</td><td><span class="badge ${t.outcome}">${t.outcome}</span></td>
        <td class="${pnlClass(t.pnl_dollar)}" style="font-weight:700">${fmt(t.pnl_dollar)}</td>
      </tr>`).join('')}</tbody>
    </table></div>
    <button class="btn btn-secondary" style="margin-top:14px" onclick="closeModal()">Close</button>`;
  $('#modal-overlay').classList.remove('hidden');
}

// === Eval Page with Monte Carlo ===
let evalStartDate = '';

function setEvalDate(val) {
  evalStartDate = val;
  loadEval();
}

async function loadEval() {
  const param = evalStartDate ? `?start_date=${evalStartDate}` : '';
  const [ev, mc, dailyData] = await Promise.all([
    api('/api/eval' + param),
    api('/api/eval/monte_carlo'),
    api('/api/stats/daily'),
  ]);

  const statusLabel = ev.status === 'pass' ? 'PASSED' : ev.status === 'fail' ? 'FAILED' : 'IN PROGRESS';
  const statusClass = ev.status === 'pass' ? 'pass' : ev.status === 'fail' ? 'fail' : 'in_progress';
  const progressPct = ev.progress_pct || 0;
  const ddPct = ev.dd_pct || 0;

  // Consistency rule
  let consistencyPass = true;
  let consistencyMsg = '';
  if (dailyData.daily && dailyData.daily.length > 0) {
    const totalProfit = dailyData.daily.reduce((s, d) => s + (d.pnl > 0 ? d.pnl : 0), 0);
    const maxDay = Math.max(...dailyData.daily.map(d => d.pnl));
    if (totalProfit > 0 && maxDay > totalProfit * 0.5) {
      consistencyPass = false;
      consistencyMsg = `Best day ($${maxDay.toFixed(0)}) exceeds 50% of total profit ($${totalProfit.toFixed(0)})`;
    } else {
      consistencyMsg = `Best day: $${maxDay.toFixed(0)} / Total profit: $${totalProfit.toFixed(0)} — within 50% rule`;
    }
  }

  $('#page-eval').innerHTML = `
    <h1>Eval Simulator</h1>

    <div class="toolbar">
      <label style="color:var(--text2);font-size:.8em">Start Date:</label>
      <input type="date" value="${evalStartDate}" onchange="setEvalDate(this.value)" style="max-width:160px">
      <button class="btn btn-secondary" onclick="setEvalDate('')">Reset</button>
      <span style="margin-left:auto"><span class="eval-status-badge ${statusClass}">${statusLabel}</span></span>
    </div>

    ${ev.fail_reason ? `<div style="color:var(--red);font-size:.82em;margin-bottom:12px;padding:10px 14px;border:1px solid rgba(255,255,255,0.12);border-radius:var(--radius);background:var(--red-dim)">${ev.fail_reason}</div>` : ''}

    <div class="consistency-check ${consistencyPass ? 'pass' : 'fail'}">
      <span style="font-weight:700">${consistencyPass ? '✓' : '✗'} Consistency Rule (50%)</span>
      <span style="opacity:0.8;font-size:.82em">${consistencyMsg}</span>
    </div>

    <div class="stats-grid" style="margin-bottom:16px">
      <div class="stat-card"><div class="label">Total P&L</div><div class="value ${pnlClass(ev.total_pnl)}">${fmt(ev.total_pnl)}</div></div>
      <div class="stat-card"><div class="label">Peak Equity</div><div class="value">${fmt(ev.peak)}</div></div>
      <div class="stat-card"><div class="label">Max Drawdown</div><div class="value red">-${fmtDollar(ev.drawdown)}</div></div>
      <div class="stat-card"><div class="label">Trading Days</div><div class="value cyan">${ev.days}</div></div>
    </div>

    <div class="section">
      <div class="chart-box">
        <h2>Progress to Target</h2>
        <div class="progress-bar" style="margin-top:10px">
          <div class="progress-fill green-fill" style="width:${progressPct}%"></div>
          <div class="progress-label">${fmt(ev.total_pnl)} / $${(ev.target||3000).toLocaleString()} (${progressPct}%)</div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="chart-box">
        <h2>Drawdown Usage</h2>
        <div class="progress-bar" style="margin-top:10px">
          <div class="progress-fill red-fill" style="width:${ddPct}%"></div>
          <div class="progress-label">-${fmtDollar(ev.drawdown)} / $${(ev.max_dd||2000).toLocaleString()} (${ddPct}%)</div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="chart-box">
        <h2>Monte Carlo Simulation</h2>
        <div class="mc-params">
          <div class="mc-param-group"><label>Target ($)</label><input type="number" id="mcTarget" value="3000"></div>
          <div class="mc-param-group"><label>Max DD ($)</label><input type="number" id="mcMaxDD" value="2000"></div>
          <div class="mc-param-group"><label>Green Risk ($)</label><input type="number" id="mcGreenRisk" value="500"></div>
          <div class="mc-param-group"><label>Red Risk ($)</label><input type="number" id="mcRedRisk" value="250"></div>
          <div class="mc-param-group"><label>Simulations</label>
            <select id="mcSimCount">
              <option value="1000">1,000</option>
              <option value="5000" selected>5,000</option>
              <option value="10000">10,000</option>
            </select>
          </div>
        </div>
        <div style="margin-bottom:16px">
          <button class="btn btn-accent" onclick="runMonteCarlo()" id="mcRunBtn">▶ Run Simulation</button>
          <span id="mcStatus" style="color:var(--text3);font-size:.78em;margin-left:10px"></span>
        </div>
        <div id="mcResultsArea"></div>
        <canvas id="mcChart" height="100" style="margin-top:12px"></canvas>
      </div>
    </div>

    <div class="section">
      <div class="table-wrap">
        <table>
          <thead><tr><th>Rule</th><th>Value</th><th>Status</th></tr></thead>
          <tbody>
            <tr><td>Profit Target</td><td>$${(ev.target||3000).toLocaleString()}</td><td>${progressPct >= 100 ? '<span class="badge win">Hit</span>' : `${progressPct}%`}</td></tr>
            <tr><td>Max EOD Drawdown</td><td>$${(ev.max_dd||2000).toLocaleString()}</td><td>${ev.status === 'fail' ? '<span class="badge loss">Breached</span>' : '<span style="color:var(--text2)">OK</span>'}</td></tr>
            <tr><td>Risk Per Trade</td><td>$${ev.risk||500}</td><td><span style="color:var(--text2)">—</span></td></tr>
            <tr><td>Consistency (50%)</td><td>Largest day ≤ 50% profit</td><td>${consistencyPass ? '<span class="badge win">Pass</span>' : '<span class="badge loss">Fail</span>'}</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <hr style="border:none;border-top:1px solid rgba(255,255,255,0.06);margin:32px 0">

    <h2 style="margin-bottom:16px">PropFirm Lifecycle Simulator</h2>
    <p style="color:var(--text3);font-size:.78em;margin-bottom:16px">Full lifecycle: Eval → Funded (buffer) → Payout cycle. DD floor resets to $50,100 after each payout.</p>
    <div class="pf-params-grid">
      <div class="mc-param-group"><label>Eval Cost ($)</label><input type="number" id="pf_eval_cost" value="155"></div>
      <div class="mc-param-group"><label>Eval Target ($)</label><input type="number" id="pf_eval_target" value="3000"></div>
      <div class="mc-param-group"><label>Eval Max DD ($)</label><input type="number" id="pf_eval_max_dd" value="2000"></div>
      <div class="mc-param-group"><label>Funded Start ($)</label><input type="number" id="pf_funded_start" value="50000"></div>
      <div class="mc-param-group"><label>Buffer Target ($)</label><input type="number" id="pf_buffer_target" value="5000"></div>
      <div class="mc-param-group"><label>Payout Amount ($)</label><input type="number" id="pf_payout_amount" value="2500"></div>
      <div class="mc-param-group"><label>Payout Split</label><input type="number" id="pf_payout_split" value="0.80" step="0.01"></div>
      <div class="mc-param-group"><label>DD Floor ($)</label><input type="number" id="pf_dd_floor" value="50100"></div>
      <div class="mc-param-group"><label>Risk Green ($)</label><input type="number" id="pf_risk_green" value="500"></div>
      <div class="mc-param-group"><label>Risk Drawdown ($)</label><input type="number" id="pf_risk_drawdown" value="250"></div>
      <div class="mc-param-group"><label>DD Threshold ($)</label><input type="number" id="pf_dd_threshold" value="500"></div>
      <div class="mc-param-group"><label>Simulations</label>
        <select id="pf_num_sims">
          <option value="1000">1,000</option>
          <option value="5000" selected>5,000</option>
          <option value="10000">10,000</option>
        </select>
      </div>
      <div class="mc-param-group"><label>Months</label><input type="number" id="pf_sim_months" value="12"></div>
      <input type="hidden" id="pf_base_risk" value="200">
    </div>
    <div style="margin:16px 0">
      <button class="btn btn-accent" onclick="runPropFirmSim()" id="pfRunBtn">▶ Run Lifecycle Simulation</button>
      <span id="pfStatus" style="color:var(--text3);font-size:.78em;margin-left:10px"></span>
    </div>
    <div id="pfResultsArea"></div>
    <div class="section"><div class="chart-box"><h2>Cumulative Income Paths</h2><canvas id="pfChart" height="120"></canvas></div></div>`;

  window._mcPnls = mc.pnls || [];
  window._pfPnls = mc.pnls || [];
}

async function runMonteCarlo() {
  const pnls = window._mcPnls;
  if (!pnls || pnls.length < 5) {
    document.getElementById('mcStatus').textContent = 'Need at least 5 trades';
    return;
  }

  const target = parseFloat(document.getElementById('mcTarget').value) || 3000;
  const maxDD = parseFloat(document.getElementById('mcMaxDD').value) || 2000;
  const simCount = parseInt(document.getElementById('mcSimCount').value) || 5000;

  document.getElementById('mcRunBtn').disabled = true;
  document.getElementById('mcStatus').textContent = 'Running...';

  await new Promise(r => setTimeout(r, 50));

  const maxTrades = 500;
  let passCount = 0;
  let blowCount = 0;
  let passedDays = [];
  const displayPaths = [];
  const displayCount = 50;

  for (let sim = 0; sim < simCount; sim++) {
    let equity = 0;
    let peak = 0;
    let passed = false;
    let blown = false;
    const path = sim < displayCount ? [0] : null;

    for (let t = 0; t < maxTrades; t++) {
      const rawPnl = pnls[Math.floor(Math.random() * pnls.length)];
      equity += rawPnl;
      if (equity > peak) peak = equity;
      const currentDD = peak - equity;
      if (path) path.push(equity);
      if (currentDD >= maxDD) { blown = true; break; }
      if (equity >= target) { passed = true; passedDays.push(t + 1); break; }
    }

    if (passed) passCount++;
    if (blown) blowCount++;
    if (path) displayPaths.push(path);
  }

  const passRate = (passCount / simCount * 100).toFixed(1);
  const blowRate = (blowCount / simCount * 100).toFixed(1);
  const avgDays = passedDays.length > 0 ? (passedDays.reduce((a,b) => a+b, 0) / passedDays.length).toFixed(0) : '—';
  const medianDays = passedDays.length > 0 ? passedDays.sort((a,b) => a-b)[Math.floor(passedDays.length/2)] : '—';

  document.getElementById('mcResultsArea').innerHTML = `
    <div class="mc-results-grid">
      <div class="mc-result-card"><div class="mc-label">Pass Rate</div><div class="mc-val" style="color:var(--green)">${passRate}%</div></div>
      <div class="mc-result-card"><div class="mc-label">Blow Rate</div><div class="mc-val" style="color:var(--red)">${blowRate}%</div></div>
      <div class="mc-result-card"><div class="mc-label">Avg Trades to Pass</div><div class="mc-val">${avgDays}</div></div>
      <div class="mc-result-card"><div class="mc-label">Median Trades</div><div class="mc-val">${medianDays}</div></div>
    </div>`;

  const maxLen = Math.max(...displayPaths.map(p => p.length));
  const labels = Array.from({length: maxLen}, (_, i) => i);

  const datasets = displayPaths.map(path => {
    const lastVal = path[path.length - 1];
    const color = lastVal >= target ? 'rgba(255,255,255,0.12)' : lastVal <= -maxDD ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.06)';
    return { data: path, borderColor: color, borderWidth: 1, pointRadius: 0, tension: 0.1, fill: false };
  });

  datasets.push({ data: Array(maxLen).fill(target), borderColor: 'rgba(255,255,255,0.35)', borderDash: [6,4], borderWidth: 1.5, pointRadius: 0, fill: false });
  datasets.push({ data: Array(maxLen).fill(-maxDD), borderColor: 'rgba(255,255,255,0.35)', borderDash: [6,4], borderWidth: 1.5, pointRadius: 0, fill: false });

  makeChart('mcChart', {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { x: { display: false }, y: { grid: { color: 'rgba(48,54,61,0.4)' }, ticks: { callback: v => '$' + v.toLocaleString() } } },
      animation: false,
    }
  });

  document.getElementById('mcRunBtn').disabled = false;
  document.getElementById('mcStatus').textContent = `${simCount.toLocaleString()} simulations completed`;
}

// PropFirm sim is now merged into the Eval page (loadEval above)

function runPropFirmSim() {
  const pnls = window._pfPnls;
  if (!pnls || pnls.length < 5) { $('#pfStatus').textContent = 'Need at least 5 trades'; return; }

  const P = {
    eval_cost: +$('#pf_eval_cost').value,
    eval_target: +$('#pf_eval_target').value,
    eval_max_dd: +$('#pf_eval_max_dd').value,
    funded_start: +$('#pf_funded_start').value,
    buffer_target: +$('#pf_buffer_target').value,
    payout_amount: +$('#pf_payout_amount').value,
    payout_split: +$('#pf_payout_split').value,
    dd_floor: +$('#pf_dd_floor').value,
    risk_green: +$('#pf_risk_green').value,
    risk_drawdown: +$('#pf_risk_drawdown').value,
    dd_threshold: +$('#pf_dd_threshold').value,
    num_sims: +$('#pf_num_sims').value,
    sim_months: +$('#pf_sim_months').value,
    base_risk: +$('#pf_base_risk').value,
  };

  const totalDays = Math.round(P.sim_months * 21.7); // trading days
  const tradeWeights = [0.50, 0.35, 0.15]; // 1,2,3 trades per day

  $('#pfRunBtn').disabled = true;
  $('#pfStatus').textContent = 'Running...';

  setTimeout(() => {
    const allResults = [];
    const displayPaths = [];
    const DISPLAY_COUNT = 50;

    for (let s = 0; s < P.num_sims; s++) {
      let phase = 1; // 1=eval, 2=funded-buffer, 3=payout-cycle
      let equity = 0;       // eval equity (phase 1)
      let balance = 0;      // funded balance (phase 2,3)
      let peak = 0;         // trailing peak
      let dd_limit = 0;     // current drawdown limit
      let totalIncome = 0;  // net cash received
      let totalEvalCosts = 0;
      let evalRestarts = 0;
      let totalPayouts = 0;
      let payoutCount = 0;
      let firstPayoutDay = -1;
      let evalDays = 0;
      let evalPassed = false;
      let fundedSurvived = false; // reached first payout without blowing
      let dayOfFirstPayout = -1;
      const incomePath = [0];

      // Start first eval
      totalEvalCosts += P.eval_cost;
      totalIncome -= P.eval_cost;

      for (let day = 0; day < totalDays; day++) {
        // Determine trades this day
        const r = Math.random();
        const numTrades = r < tradeWeights[0] ? 1 : r < tradeWeights[0] + tradeWeights[1] ? 2 : 3;

        for (let t = 0; t < numTrades; t++) {
          const rawPnl = pnls[Math.floor(Math.random() * pnls.length)];

          if (phase === 1) {
            // Eval phase
            const inDrawdown = (peak - equity) >= P.dd_threshold;
            const riskMult = inDrawdown ? P.risk_drawdown / P.base_risk : P.risk_green / P.base_risk;
            const scaledPnl = rawPnl * riskMult;
            equity += scaledPnl;
            if (equity > peak) peak = equity;
          } else {
            // Funded phases (2 or 3)
            const room = balance - dd_limit;
            const inDrawdown = room <= P.dd_threshold;
            const riskMult = inDrawdown ? P.risk_drawdown / P.base_risk : P.risk_green / P.base_risk;
            const scaledPnl = rawPnl * riskMult;
            balance += scaledPnl;
            if (balance > peak) peak = balance;
          }
        }

        // EOD checks
        if (phase === 1) {
          const eodDD = peak - equity;
          if (eodDD >= P.eval_max_dd) {
            // Blown eval — restart
            evalRestarts++;
            totalEvalCosts += P.eval_cost;
            totalIncome -= P.eval_cost;
            equity = 0;
            peak = 0;
          } else if (equity >= P.eval_target) {
            // Passed eval → funded
            if (!evalPassed) { evalDays = day + 1; evalPassed = true; }
            phase = 2;
            balance = P.funded_start;
            peak = P.funded_start;
            dd_limit = P.funded_start - P.eval_max_dd; // initial trailing DD from start
          }
        } else if (phase === 2) {
          // Update trailing DD limit
          dd_limit = Math.max(dd_limit, peak - P.eval_max_dd);
          if (balance <= dd_limit) {
            // Blown funded — back to eval
            evalRestarts++;
            totalEvalCosts += P.eval_cost;
            totalIncome -= P.eval_cost;
            phase = 1;
            equity = 0;
            peak = 0;
          } else if (balance >= P.funded_start + P.buffer_target) {
            // Buffer built → first payout
            fundedSurvived = true;
            phase = 3;
            // Take payout
            const payout = P.payout_amount * P.payout_split;
            totalPayouts += payout;
            totalIncome += payout;
            payoutCount++;
            if (dayOfFirstPayout < 0) dayOfFirstPayout = day + 1;
            balance -= P.payout_amount;
            dd_limit = P.dd_floor; // DD floor resets
            peak = balance; // reset peak to current balance after payout
          }
        } else if (phase === 3) {
          // Payout cycle
          if (balance <= P.dd_floor) {
            // Blown — back to eval
            evalRestarts++;
            totalEvalCosts += P.eval_cost;
            totalIncome -= P.eval_cost;
            phase = 1;
            equity = 0;
            peak = 0;
          } else if (balance >= peak + P.payout_amount) {
            // Can take another payout (buffer rebuilt to payout_amount above last payout peak)
            // Actually: take payout when buffer_target above dd_floor is reached
            // Let's use: balance >= dd_floor + P.buffer_target
          }
          // Check if can take payout: balance >= dd_floor + buffer_target
          if (phase === 3 && balance >= P.dd_floor + P.buffer_target) {
            const payout = P.payout_amount * P.payout_split;
            totalPayouts += payout;
            totalIncome += payout;
            payoutCount++;
            balance -= P.payout_amount;
            dd_limit = P.dd_floor;
            peak = balance;
          }
        }

        if (s < DISPLAY_COUNT) incomePath.push(totalIncome);
      }

      allResults.push({
        totalIncome,
        totalEvalCosts,
        evalRestarts,
        totalPayouts,
        payoutCount,
        evalPassed,
        fundedSurvived,
        evalDays,
        dayOfFirstPayout,
      });
      if (s < DISPLAY_COUNT) displayPaths.push(incomePath);
    }

    // Compute metrics
    const N = allResults.length;
    const evalPassCount = allResults.filter(r => r.evalPassed).length;
    const evalPassRate = (evalPassCount / N * 100).toFixed(1);
    const avgEvalDays = evalPassCount > 0 ? (allResults.filter(r => r.evalPassed).reduce((s, r) => s + r.evalDays, 0) / evalPassCount).toFixed(0) : '—';
    const fundedSurvivedCount = allResults.filter(r => r.fundedSurvived).length;
    const fundedSurvivalRate = (fundedSurvivedCount / N * 100).toFixed(1);
    const avgMonthlyIncome = (allResults.reduce((s, r) => s + r.totalIncome, 0) / N / P.sim_months).toFixed(0);
    const totalPayoutsAvg = (allResults.reduce((s, r) => s + r.totalPayouts, 0) / N).toFixed(0);
    const avgEvalRestarts = (allResults.reduce((s, r) => s + r.evalRestarts, 0) / N).toFixed(1);

    const firstPayoutDays = allResults.filter(r => r.dayOfFirstPayout > 0).map(r => r.dayOfFirstPayout);
    const avgFirstPayout = firstPayoutDays.length > 0 ? (firstPayoutDays.reduce((a,b) => a+b, 0) / firstPayoutDays.length).toFixed(0) : '—';

    // Probability profitable at milestones
    const milestoneDays = [21, 63, 126, totalDays]; // 1,3,6,12 months
    const milestoneLabels = ['1mo', '3mo', '6mo', '12mo'];
    const milestoneProfitable = milestoneDays.map((d, i) => {
      // Use display paths for approximation (we'd need full paths for all sims, so use allResults for final)
      if (i === milestoneDays.length - 1) {
        return (allResults.filter(r => r.totalIncome > 0).length / N * 100).toFixed(1);
      }
      // For sub-period, approximate: check if income path at that day > 0
      // Only have display paths for 50, so use final income for all
      return '—';
    });
    // Actually recalculate properly using allResults final income for 12mo
    const profitableAtEnd = (allResults.filter(r => r.totalIncome > 0).length / N * 100).toFixed(1);

    const initialInvestment = P.eval_cost * 3; // $465
    const avgTotalIncome = allResults.reduce((s, r) => s + r.totalIncome, 0) / N;
    const netROI = ((avgTotalIncome / initialInvestment) * 100).toFixed(0);

    // Avg income path for chart
    const maxLen = Math.max(...displayPaths.map(p => p.length));
    const avgPath = [];
    for (let i = 0; i < maxLen; i++) {
      let sum = 0, cnt = 0;
      for (const p of displayPaths) {
        if (i < p.length) { sum += p[i]; cnt++; }
      }
      avgPath.push(cnt > 0 ? sum / cnt : avgPath[avgPath.length - 1] || 0);
    }

    // Render results
    $('#pfResultsArea').innerHTML = `
      <div class="mc-results-grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">
        <div class="mc-result-card"><div class="mc-label">Eval Pass Rate</div><div class="mc-val" style="text-shadow:0 0 20px rgba(255,255,255,0.08)">${evalPassRate}%</div></div>
        <div class="mc-result-card"><div class="mc-label">Avg Days to Pass Eval</div><div class="mc-val" style="text-shadow:0 0 20px rgba(255,255,255,0.08)">${avgEvalDays}</div></div>
        <div class="mc-result-card"><div class="mc-label">Funded Survival Rate</div><div class="mc-val" style="text-shadow:0 0 20px rgba(255,255,255,0.08)">${fundedSurvivalRate}%</div></div>
        <div class="mc-result-card"><div class="mc-label">Avg Monthly Income</div><div class="mc-val" style="text-shadow:0 0 20px rgba(255,255,255,0.08)">$${parseInt(avgMonthlyIncome).toLocaleString()}</div></div>
        <div class="mc-result-card"><div class="mc-label">Total Payouts (avg)</div><div class="mc-val" style="text-shadow:0 0 20px rgba(255,255,255,0.08)">$${parseInt(totalPayoutsAvg).toLocaleString()}</div></div>
        <div class="mc-result-card"><div class="mc-label">Avg Eval Restarts</div><div class="mc-val" style="text-shadow:0 0 20px rgba(255,255,255,0.08)">${avgEvalRestarts}</div></div>
        <div class="mc-result-card"><div class="mc-label">Time to First Payout</div><div class="mc-val" style="text-shadow:0 0 20px rgba(255,255,255,0.08)">${avgFirstPayout} days</div></div>
        <div class="mc-result-card"><div class="mc-label">Profitable at ${P.sim_months}mo</div><div class="mc-val" style="text-shadow:0 0 20px rgba(255,255,255,0.08)">${profitableAtEnd}%</div></div>
        <div class="mc-result-card"><div class="mc-label">Net ROI (on $${initialInvestment})</div><div class="mc-val" style="text-shadow:0 0 20px rgba(255,255,255,0.08)">${netROI}%</div></div>
      </div>
    `;

    // Chart
    const labels = Array.from({length: maxLen}, (_, i) => i);
    const datasets = displayPaths.map(path => ({
      data: path,
      borderColor: 'rgba(255,255,255,0.08)',
      borderWidth: 1,
      pointRadius: 0,
      tension: 0.1,
      fill: false,
    }));
    // Average path (thick white)
    datasets.push({
      data: avgPath,
      borderColor: 'rgba(255,255,255,0.7)',
      borderWidth: 2.5,
      pointRadius: 0,
      tension: 0.1,
      fill: false,
    });
    // Reference lines
    const monthlyTargets = [1000, 2000, 3000];
    for (const mt of monthlyTargets) {
      datasets.push({
        data: labels.map(d => mt * (d / 21.7)),
        borderColor: 'rgba(255,255,255,0.15)',
        borderDash: [4, 6],
        borderWidth: 1,
        pointRadius: 0,
        fill: false,
      });
    }

    makeChart('pfChart', {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { display: true, title: { display: true, text: 'Trading Days', color: 'rgba(255,255,255,0.3)' }, ticks: { color: 'rgba(255,255,255,0.2)', maxTicksLimit: 10 }, grid: { color: 'rgba(255,255,255,0.03)' } },
          y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: 'rgba(255,255,255,0.3)', callback: v => '$' + v.toLocaleString() } },
        },
        animation: false,
      }
    });

    $('#pfRunBtn').disabled = false;
    $('#pfStatus').textContent = `${P.num_sims.toLocaleString()} simulations completed`;
  }, 50);
}

// === Risk Management ===
async function loadRisk() {
  const [s, settings] = await Promise.all([
    api('/api/stats'),
    api('/api/settings'),
  ]);

  if (!s.total) {
    $('#page-risk').innerHTML = '<h1>Risk Management</h1><p style="color:var(--text2)">No trades yet.</p>';
    return;
  }

  const greenRisk = parseFloat(settings.green_risk) || 500;
  const redRisk = parseFloat(settings.red_risk) || 250;
  const maxDDSetting = parseFloat(settings.max_dd) || 2000;
  const targetSetting = parseFloat(settings.equity_target) || 3000;

  const equity = s.total_pnl;
  const peak = s.peak_equity;
  const dd = peak - equity;
  const ddPct = peak > 0 ? (dd / peak * 100) : 0;
  const progress = Math.max(0, Math.min(100, equity / targetSetting * 100));
  const isGreen = dd < 500;
  const riskTier = isGreen ? greenRisk : redRisk;
  const ddRemaining = maxDDSetting - dd;
  const safeRisk = Math.max(0, Math.min(riskTier, ddRemaining * 0.25));

  $('#page-risk').innerHTML = `
    <h1>Risk Management</h1>

    <div class="section">
      <div class="chart-box">
        <h2>Risk Settings</h2>
        <div class="risk-config-grid">
          <div class="risk-config-item"><label>Green Risk ($)</label><input type="number" id="cfgGreenRisk" value="${greenRisk}"></div>
          <div class="risk-config-item"><label>Red Risk ($)</label><input type="number" id="cfgRedRisk" value="${redRisk}"></div>
          <div class="risk-config-item"><label>Max DD ($)</label><input type="number" id="cfgMaxDD" value="${maxDDSetting}"></div>
          <div class="risk-config-item"><label>Target ($)</label><input type="number" id="cfgTarget" value="${targetSetting}"></div>
        </div>
        <button class="btn btn-primary" onclick="saveRiskSettings()">Save Settings</button>
      </div>
    </div>

    <div class="stats-grid">
      <div class="stat-card"><div class="label">Current Equity</div><div class="value ${pnlClass(equity)}">${fmt(equity)}</div></div>
      <div class="stat-card"><div class="label">Current Drawdown</div><div class="value red">-$${dd.toFixed(2)}</div><div class="sub">${ddPct.toFixed(1)}% from peak</div></div>
      <div class="stat-card"><div class="label">Risk Tier</div><div class="value"><span class="tier-indicator ${isGreen?'tier-green':'tier-red'}">$${riskTier}</span></div></div>
      <div class="stat-card"><div class="label">Recommended Risk</div><div class="value cyan">$${safeRisk.toFixed(0)}</div><div class="sub">25% of $${ddRemaining.toFixed(0)} remaining</div></div>
    </div>

    <div class="section">
      <div class="position-sizer">
        <h2>Position Size Calculator</h2>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:16px">
          <div><label style="display:block;font-size:.58em;text-transform:uppercase;letter-spacing:.08em;color:var(--text3);font-weight:600;margin-bottom:5px">Stop Distance (pts)</label><input type="number" id="sizerStopDist" value="15" style="width:100%" oninput="calcPositionSize()"></div>
          <div><label style="display:block;font-size:.58em;text-transform:uppercase;letter-spacing:.08em;color:var(--text3);font-weight:600;margin-bottom:5px">Dollar Per Point</label><input type="number" id="sizerDPP" value="20" style="width:100%" oninput="calcPositionSize()"></div>
          <div><label style="display:block;font-size:.58em;text-transform:uppercase;letter-spacing:.08em;color:var(--text3);font-weight:600;margin-bottom:5px">Risk Amount ($)</label><input type="number" id="sizerRisk" value="${riskTier}" style="width:100%" oninput="calcPositionSize()"></div>
        </div>
        <div class="sizer-result" id="sizerResult">—</div>
      </div>
    </div>

    <div class="section">
      <div class="chart-box">
        <h2>Eval Progress</h2>
        <div class="progress-bar" style="margin-top:10px">
          <div class="progress-fill green-fill" style="width:${progress}%"></div>
          <div class="progress-label">${fmt(equity)} / $${targetSetting.toLocaleString()} (${progress.toFixed(1)}%)</div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="chart-box">
        <h2>Drawdown Over Time</h2>
        <canvas id="ddChart" height="80"></canvas>
      </div>
    </div>

    <div class="section">
      <div class="table-wrap">
      <table>
        <thead><tr><th>Rule</th><th>Risk</th><th>Condition</th><th>Status</th></tr></thead>
        <tbody>
          <tr><td style="font-weight:600">Green Tier</td><td>$${greenRisk}</td><td>DD &lt; $500</td><td>${isGreen ? '<span class="badge win">Active</span>' : '<span style="color:var(--text3)">—</span>'}</td></tr>
          <tr><td style="font-weight:600">Red Tier</td><td>$${redRisk}</td><td>DD ≥ $500</td><td>${!isGreen ? '<span class="badge loss">Active</span>' : '<span style="color:var(--text3)">—</span>'}</td></tr>
          <tr><td style="font-weight:600">Target</td><td colspan="2">$${targetSetting.toLocaleString()} profit</td><td>${progress >= 100 ? '<span class="badge win">Passed</span>' : `<span style="color:var(--text2)">${(100-progress).toFixed(1)}% left</span>`}</td></tr>
        </tbody>
      </table>
      </div>
    </div>`;

  calcPositionSize();

  // Drawdown chart
  let ddData = [];
  let peak2 = 0;
  s.equity_curve.forEach(v => {
    if (v > peak2) peak2 = v;
    ddData.push(-(peak2 - v));
  });

  let ddLabels = s.equity_labels;
  if (ddData.length > 500) {
    const step = Math.ceil(ddData.length / 500);
    ddData = ddData.filter((_,i) => i % step === 0);
    ddLabels = ddLabels.filter((_,i) => i % step === 0);
  }

  makeChart('ddChart', {
    type:'line',
    data:{ labels:ddLabels, datasets:[{
      data:ddData, borderColor:'rgba(255,255,255,0.5)', backgroundColor:'rgba(255,255,255,0.06)',
      fill:true, pointRadius:0, borderWidth:1.5
    }]},
    options:{ responsive:true, plugins:{legend:{display:false}}, scales:{
      x:{display:false}, y:{grid:{color:'rgba(48,54,61,0.4)'},ticks:{callback:v=>'$'+v.toLocaleString()}}
    }}
  });
}

function calcPositionSize() {
  const stopDist = parseFloat(document.getElementById('sizerStopDist')?.value) || 0;
  const dpp = parseFloat(document.getElementById('sizerDPP')?.value) || 0;
  const risk = parseFloat(document.getElementById('sizerRisk')?.value) || 0;
  const el = document.getElementById('sizerResult');
  if (!el) return;
  if (stopDist <= 0 || dpp <= 0) { el.textContent = '—'; return; }
  const dollarRiskPerContract = stopDist * dpp;
  const contracts = Math.floor(risk / dollarRiskPerContract);
  el.innerHTML = `<span style="color:var(--text)">${contracts}</span> <span style="font-size:0.4em;color:var(--text3);font-weight:500">contracts</span><br><span style="font-size:0.35em;color:var(--text3)">$${dollarRiskPerContract.toFixed(0)}/contract × ${contracts} = $${(dollarRiskPerContract * contracts).toFixed(0)} risk</span>`;
}

async function saveRiskSettings() {
  const body = {
    green_risk: parseFloat(document.getElementById('cfgGreenRisk').value),
    red_risk: parseFloat(document.getElementById('cfgRedRisk').value),
    max_dd: parseFloat(document.getElementById('cfgMaxDD').value),
    target: parseFloat(document.getElementById('cfgTarget').value),
  };
  await fetch('/api/settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  loadRisk();
}

// === Init ===
loadDashboard();
