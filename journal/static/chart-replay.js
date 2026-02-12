// === Chart Replay Page — Pure HTML5 Canvas ===
let _cr = {
  canvas: null, ctx: null,
  allCandles: [], visibleCandles: [],
  index: 0, playing: false, timer: null, speed: 1,
  trade: null, exitMarkerSet: false,
  // View state
  offsetX: 0, candleWidth: 8, gap: 3,
  dragStart: null, dragging: false,
  mouse: { x: -1, y: -1 },
  // Layout
  padRight: 70, padBottom: 40, padTop: 10, padLeft: 5,
};

function loadChartReplay(tradeId) {
  const page = document.getElementById('page-chart');
  page.innerHTML = `
    <div class="page-header"><h1>Chart Replay</h1></div>
    <div class="chart-replay-controls">
      <select id="chart-trade-select" class="cr-select"><option value="">Select a trade...</option></select>
      <div class="cr-buttons">
        <button id="cr-play" class="cr-btn" disabled>▶ Play</button>
        <button id="cr-reset" class="cr-btn" disabled>⟲ Reset</button>
        <span class="cr-speed-label">Speed:</span>
        <select id="cr-speed" class="cr-select cr-speed-select">
          <option value="1">1x</option><option value="2">2x</option><option value="5">5x</option><option value="10">10x</option>
        </select>
      </div>
    </div>
    <div id="chart-trade-info" class="cr-info hidden"></div>
    <div id="chart-container" style="width:100%;height:calc(100vh - 220px);min-height:400px;background:#000;border-radius:8px;overflow:hidden;position:relative;">
      <canvas id="cr-canvas" style="display:block;width:100%;height:100%;"></canvas>
    </div>
  `;

  const canvas = document.getElementById('cr-canvas');
  _cr.canvas = canvas;
  _cr.ctx = canvas.getContext('2d');

  // Resize handler
  function resize() {
    const cont = document.getElementById('chart-container');
    if (!cont) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = cont.clientWidth * dpr;
    canvas.height = cont.clientHeight * dpr;
    _cr.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    _cr.W = cont.clientWidth;
    _cr.H = cont.clientHeight;
    drawChart();
  }
  window._crResize = resize;
  window.addEventListener('resize', resize);
  setTimeout(resize, 50);

  // Mouse events
  canvas.addEventListener('mousemove', e => {
    const r = canvas.getBoundingClientRect();
    _cr.mouse.x = e.clientX - r.left;
    _cr.mouse.y = e.clientY - r.top;
    if (_cr.dragging && _cr.dragStart !== null) {
      _cr.offsetX += e.clientX - _cr.dragStart;
      _cr.dragStart = e.clientX;
    }
    drawChart();
  });
  canvas.addEventListener('mouseleave', () => { _cr.mouse.x = -1; _cr.mouse.y = -1; _cr.dragging = false; drawChart(); });
  canvas.addEventListener('mousedown', e => { _cr.dragging = true; _cr.dragStart = e.clientX; });
  canvas.addEventListener('mouseup', () => { _cr.dragging = false; });
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -1 : 1;
    const oldW = _cr.candleWidth;
    _cr.candleWidth = Math.max(2, Math.min(30, _cr.candleWidth + delta));
    // Adjust offset to zoom towards mouse
    const chartW = _cr.W - _cr.padLeft - _cr.padRight;
    const mouseRatio = (_cr.mouse.x - _cr.padLeft) / chartW;
    const oldTotal = _cr.visibleCandles.length * (oldW + _cr.gap);
    const newTotal = _cr.visibleCandles.length * (_cr.candleWidth + _cr.gap);
    _cr.offsetX += (oldTotal - newTotal) * mouseRatio;
    drawChart();
  }, { passive: false });

  // Load trades
  api('/api/trades/all').then(data => {
    const select = document.getElementById('chart-trade-select');
    data.trades.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t.id;
      const d = t.entry_time.substring(0, 10);
      const pnl = t.pnl_dollar >= 0 ? `+$${t.pnl_dollar.toFixed(0)}` : `-$${Math.abs(t.pnl_dollar).toFixed(0)}`;
      opt.textContent = `#${t.id} ${d} ${t.instrument} ${t.direction.toUpperCase()} → ${t.outcome} (${pnl})`;
      if (t.outcome === 'win') opt.style.color = '#4ade80';
      else opt.style.color = '#f87171';
      select.appendChild(opt);
    });
    if (tradeId) { select.value = tradeId; _loadTradeCanvas(tradeId); }
    select.addEventListener('change', () => { if (select.value) _loadTradeCanvas(parseInt(select.value)); });
  });

  document.getElementById('cr-play').addEventListener('click', _toggleReplay);
  document.getElementById('cr-reset').addEventListener('click', _resetReplay);
  document.getElementById('cr-speed').addEventListener('change', e => {
    _cr.speed = parseInt(e.target.value);
    if (_cr.playing) { clearInterval(_cr.timer); _startReplayTimer(); }
  });
}

async function _loadTradeCanvas(tradeId) {
  _stopReplay();
  const data = await fetch(`/api/trade/${tradeId}/candles`).then(r => r.json());
  if (data.detail) { alert(data.detail); return; }

  _cr.trade = data.trade;
  _cr.allCandles = data.candles;
  _cr.exitMarkerSet = false;

  // Show all candles initially
  _cr.visibleCandles = _cr.allCandles.slice();
  _cr.index = _cr.allCandles.length;
  _cr.offsetX = 0;

  // Trade info panel
  const trade = _cr.trade;
  const info = document.getElementById('chart-trade-info');
  info.classList.remove('hidden');
  const rr = trade.sl_price && trade.entry_price ?
    (Math.abs(trade.tp_price - trade.entry_price) / Math.abs(trade.sl_price - trade.entry_price)).toFixed(1) : (trade.rr_target?.toFixed(1) || '—');
  const oc = trade.outcome === 'win' ? 'green' : 'red';
  info.innerHTML = `
    <div class="cr-info-item"><span class="cr-label">Instrument</span><span>${trade.instrument}</span></div>
    <div class="cr-info-item"><span class="cr-label">Direction</span><span>${trade.direction.toUpperCase()}</span></div>
    <div class="cr-info-item"><span class="cr-label">Entry</span><span>${trade.entry_price}</span></div>
    <div class="cr-info-item"><span class="cr-label">Exit</span><span>${trade.exit_price || '—'}</span></div>
    <div class="cr-info-item"><span class="cr-label">SL</span><span style="color:#f87171">${trade.sl_price}</span></div>
    <div class="cr-info-item"><span class="cr-label">TP</span><span style="color:#4ade80">${trade.tp_price}</span></div>
    <div class="cr-info-item"><span class="cr-label">R:R</span><span>${rr}</span></div>
    <div class="cr-info-item"><span class="cr-label">P&L</span><span class="${oc}">${trade.pnl_dollar >= 0 ? '+' : ''}$${trade.pnl_dollar.toFixed(2)}</span></div>
    <div class="cr-info-item"><span class="cr-label">Outcome</span><span class="${oc}">${trade.outcome.toUpperCase()}</span></div>
  `;

  // Fit to view
  _fitView();
  document.getElementById('cr-play').disabled = false;
  document.getElementById('cr-reset').disabled = false;
  drawChart();
}

function _fitView() {
  const chartW = _cr.W - _cr.padLeft - _cr.padRight;
  const n = _cr.visibleCandles.length;
  if (n === 0) return;
  const totalW = n * (_cr.candleWidth + _cr.gap);
  if (totalW < chartW) {
    _cr.offsetX = 0;
  } else {
    _cr.offsetX = -(totalW - chartW);
  }
}

function drawChart() {
  const ctx = _cr.ctx;
  const W = _cr.W, H = _cr.H;
  if (!ctx || !W) return;
  const { padRight, padBottom, padTop, padLeft } = _cr;
  const chartW = W - padLeft - padRight;
  const chartH = H - padTop - padBottom;

  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, W, H);

  const candles = _cr.visibleCandles;
  if (candles.length === 0) {
    ctx.fillStyle = '#555';
    ctx.font = '14px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Select a trade to view chart', W / 2, H / 2);
    return;
  }

  // Grid lines
  ctx.strokeStyle = 'rgba(255,255,255,0.04)';
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    const y = padTop + (chartH / 5) * i;
    ctx.beginPath(); ctx.moveTo(padLeft, y); ctx.lineTo(padLeft + chartW, y); ctx.stroke();
  }

  // Price range
  const step = _cr.candleWidth + _cr.gap;
  // Find visible candle indices
  const firstVis = Math.max(0, Math.floor((-_cr.offsetX - padLeft) / step));
  const lastVis = Math.min(candles.length - 1, Math.ceil((-_cr.offsetX - padLeft + chartW) / step));

  let pMin = Infinity, pMax = -Infinity;
  for (let i = firstVis; i <= lastVis; i++) {
    if (candles[i].low < pMin) pMin = candles[i].low;
    if (candles[i].high > pMax) pMax = candles[i].high;
  }
  // Include trade lines in range
  const trade = _cr.trade;
  if (trade) {
    if (trade.entry_price) { pMin = Math.min(pMin, trade.entry_price); pMax = Math.max(pMax, trade.entry_price); }
    if (trade.sl_price) { pMin = Math.min(pMin, trade.sl_price); pMax = Math.max(pMax, trade.sl_price); }
    if (trade.tp_price) { pMin = Math.min(pMin, trade.tp_price); pMax = Math.max(pMax, trade.tp_price); }
  }
  const pRange = pMax - pMin || 1;
  const margin = pRange * 0.05;
  pMin -= margin; pMax += margin;
  const totalRange = pMax - pMin;

  function priceToY(p) { return padTop + (1 - (p - pMin) / totalRange) * chartH; }
  function yToPrice(y) { return pMin + (1 - (y - padTop) / chartH) * totalRange; }

  // Determine decimal places from price
  const samplePrice = candles[0].close;
  const decimals = samplePrice < 10 ? 4 : samplePrice < 1000 ? 2 : 0;

  // Draw trade lines
  if (trade) {
    function drawDashedLine(price, color, label) {
      const y = priceToY(price);
      if (y < padTop || y > padTop + chartH) return;
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.setLineDash([6, 4]);
      ctx.beginPath(); ctx.moveTo(padLeft, y); ctx.lineTo(padLeft + chartW, y); ctx.stroke();
      ctx.setLineDash([]);
      // Label on right
      ctx.fillStyle = color;
      ctx.font = '10px Inter, sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(`${label} ${price.toFixed(decimals)}`, padLeft + chartW + 4, y + 3);
      ctx.restore();
    }
    if (trade.entry_price) drawDashedLine(trade.entry_price, 'rgba(255,255,255,0.7)', 'Entry');
    if (trade.sl_price) drawDashedLine(trade.sl_price, '#f87171', 'SL');
    if (trade.tp_price) drawDashedLine(trade.tp_price, '#4ade80', 'TP');
  }

  // Draw candles
  ctx.save();
  ctx.beginPath();
  ctx.rect(padLeft, padTop, chartW, chartH);
  ctx.clip();

  for (let i = firstVis; i <= lastVis; i++) {
    const c = candles[i];
    const x = padLeft + _cr.offsetX + i * step + step / 2;
    const isUp = c.close >= c.open;
    const color = isUp ? '#fff' : '#555';
    const bodyTop = priceToY(Math.max(c.open, c.close));
    const bodyBot = priceToY(Math.min(c.open, c.close));
    const bodyH = Math.max(1, bodyBot - bodyTop);

    // Wick
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, priceToY(c.high));
    ctx.lineTo(x, priceToY(c.low));
    ctx.stroke();

    // Body
    ctx.fillStyle = color;
    ctx.fillRect(x - _cr.candleWidth / 2, bodyTop, _cr.candleWidth, bodyH);
  }

  // Entry/exit markers
  if (trade) {
    function drawMarker(time, isEntry, direction, color) {
      // Find candle index closest to time
      let idx = -1;
      for (let i = 0; i < candles.length; i++) {
        if (candles[i].time >= time) { idx = i; break; }
      }
      if (idx < 0) idx = candles.length - 1;
      const c = candles[idx];
      const x = padLeft + _cr.offsetX + idx * step + step / 2;
      const isBelow = (isEntry && direction === 'long') || (!isEntry && direction !== 'long');
      const tipY = isBelow ? priceToY(c.low) + 12 : priceToY(c.high) - 12;
      const baseY = isBelow ? tipY + 10 : tipY - 10;

      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(x, isBelow ? baseY : tipY);
      ctx.lineTo(x - 5, isBelow ? tipY : baseY);
      ctx.lineTo(x + 5, isBelow ? tipY : baseY);
      ctx.closePath();
      ctx.fill();

      ctx.fillStyle = color;
      ctx.font = 'bold 9px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(isEntry ? 'Entry' : 'Exit', x, isBelow ? baseY + 10 : tipY - 4);
    }

    if (trade.entry_time) drawMarker(trade.entry_time, true, trade.direction, '#fff');
    if (_cr.exitMarkerSet && trade.exit_time) {
      const exitColor = trade.outcome === 'win' ? '#4ade80' : '#f87171';
      drawMarker(trade.exit_time, false, trade.direction, exitColor);
    }
    // Show exit if we've shown all candles (non-replay mode)
    if (_cr.index >= _cr.allCandles.length && trade.exit_time) {
      const exitColor = trade.outcome === 'win' ? '#4ade80' : '#f87171';
      drawMarker(trade.exit_time, false, trade.direction, exitColor);
    }
  }

  ctx.restore();

  // Price axis (right)
  ctx.fillStyle = 'rgba(255,255,255,0.5)';
  ctx.font = '10px Inter, sans-serif';
  ctx.textAlign = 'left';
  const nTicks = Math.floor(chartH / 40);
  for (let i = 0; i <= nTicks; i++) {
    const p = pMin + (totalRange / nTicks) * i;
    const y = priceToY(p);
    ctx.fillText(p.toFixed(decimals), padLeft + chartW + 4, y + 3);
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(padLeft, y); ctx.lineTo(padLeft + chartW, y); ctx.stroke();
  }

  // Time axis (bottom)
  ctx.fillStyle = 'rgba(255,255,255,0.5)';
  ctx.font = '10px Inter, sans-serif';
  ctx.textAlign = 'center';
  const labelEvery = Math.max(1, Math.floor(60 / step));
  for (let i = firstVis; i <= lastVis; i += labelEvery) {
    const c = candles[i];
    const x = padLeft + _cr.offsetX + i * step + step / 2;
    const d = new Date(c.time * 1000);
    const hh = String(d.getUTCHours()).padStart(2, '0');
    const mm = String(d.getUTCMinutes()).padStart(2, '0');
    ctx.fillText(`${hh}:${mm}`, x, H - padBottom + 14);
  }

  // Crosshair
  if (_cr.mouse.x > padLeft && _cr.mouse.x < padLeft + chartW && _cr.mouse.y > padTop && _cr.mouse.y < padTop + chartH) {
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.2)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    // Horizontal
    ctx.beginPath(); ctx.moveTo(padLeft, _cr.mouse.y); ctx.lineTo(padLeft + chartW, _cr.mouse.y); ctx.stroke();
    // Vertical
    ctx.beginPath(); ctx.moveTo(_cr.mouse.x, padTop); ctx.lineTo(_cr.mouse.x, padTop + chartH); ctx.stroke();
    ctx.setLineDash([]);

    // Price label
    const hoverPrice = yToPrice(_cr.mouse.y);
    ctx.fillStyle = '#fff';
    ctx.fillRect(padLeft + chartW, _cr.mouse.y - 8, padRight, 16);
    ctx.fillStyle = '#000';
    ctx.font = '10px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(hoverPrice.toFixed(decimals), padLeft + chartW + 4, _cr.mouse.y + 3);

    // Time label
    const hoverIdx = Math.round((_cr.mouse.x - padLeft - _cr.offsetX - step / 2) / step);
    if (hoverIdx >= 0 && hoverIdx < candles.length) {
      const hc = candles[hoverIdx];
      const hd = new Date(hc.time * 1000);
      const timeStr = `${String(hd.getUTCHours()).padStart(2,'0')}:${String(hd.getUTCMinutes()).padStart(2,'0')}`;
      const tx = padLeft + _cr.offsetX + hoverIdx * step + step / 2;
      ctx.fillStyle = '#fff';
      ctx.fillRect(tx - 20, padTop + chartH, 40, 16);
      ctx.fillStyle = '#000';
      ctx.textAlign = 'center';
      ctx.fillText(timeStr, tx, padTop + chartH + 12);
    }
    ctx.restore();
  }
}

function _toggleReplay() { if (_cr.playing) _stopReplay(); else _startReplay(); }

function _startReplay() {
  if (_cr.index >= _cr.allCandles.length) return;
  _cr.playing = true;
  document.getElementById('cr-play').textContent = '⏸ Pause';
  _startReplayTimer();
}

function _startReplayTimer() {
  const interval = Math.max(10, 100 / _cr.speed);
  _cr.timer = setInterval(() => {
    if (_cr.index >= _cr.allCandles.length) { _stopReplay(); return; }
    _cr.visibleCandles = _cr.allCandles.slice(0, _cr.index + 1);
    _cr.index++;
    // Check for exit marker
    const trade = _cr.trade;
    if (trade && trade.exit_time && !_cr.exitMarkerSet) {
      const lastTime = _cr.visibleCandles[_cr.visibleCandles.length - 1].time;
      if (lastTime >= trade.exit_time) _cr.exitMarkerSet = true;
    }
    _fitView();
    drawChart();
  }, interval);
}

function _stopReplay() {
  _cr.playing = false;
  clearInterval(_cr.timer);
  const btn = document.getElementById('cr-play');
  if (btn) btn.textContent = '▶ Play';
}

function _resetReplay() {
  _stopReplay();
  _cr.exitMarkerSet = false;
  const preEntry = Math.min(60, _cr.allCandles.length);
  _cr.visibleCandles = _cr.allCandles.slice(0, preEntry);
  _cr.index = preEntry;
  _cr.offsetX = 0;
  _fitView();
  drawChart();
}

window.openChartReplay = function(tradeId) {
  switchPage('chart');
  setTimeout(() => loadChartReplay(tradeId), 50);
};
