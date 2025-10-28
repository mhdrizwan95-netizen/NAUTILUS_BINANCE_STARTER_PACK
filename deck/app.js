(function(){
  const $ = (sel)=>document.querySelector(sel);
  const ws = new WebSocket((location.protocol==='https:'?'wss://':'ws://') + location.host + '/ws');
  const weightsDiv = $("#weights");
  const topsTBody = $("#tops tbody");
  const state = {
    mode: 'yellow',
    kill: false,
    strategies: {},
    metrics: {},
    top_symbols: [],
    pnl_by_strategy: {}
  };

  $("#mode").addEventListener("change", async (e)=>{
    await fetch('/risk/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:e.target.value})});
  });
  $("#killswitch").addEventListener("click", async ()=>{
    const curr = $("#killswitch").dataset.state==='on';
    const next = !curr;
    await fetch('/kill',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:next})});
    setKill(next);
  });

  function setKill(on){
    $("#killswitch").dataset.state = on?'on':'off';
    $("#killswitch").textContent = on?'KILL ON':'KILL OFF';
    $("#killswitch").classList.toggle('danger', on);
  }

  function render(){
    $("#mode").value = state.mode || 'yellow';
    setKill(!!state.kill);
    $("#equity").textContent = 'Equity: $' + (state.metrics?.equity_usd?.toFixed?.(2) ?? '-');
    $("#pnl24").textContent = 'PnL 24h: $' + (state.metrics?.pnl_24h?.toFixed?.(2) ?? '-');
    $("#dd").textContent = 'Drawdown: ' + ((state.metrics?.drawdown_pct??0)*100).toFixed(2) + '%';
    $("#riskuse").textContent = 'Open Risk: ' + ((state.metrics?.open_risk_sum_pct??0)*100).toFixed(2) + '%';
    $("#positions").textContent = 'Positions: ' + (state.metrics?.open_positions ?? '-');
    $("#lat50").textContent = (state.metrics?.tick_to_order_ms_p50 ?? '-') ;
    $("#lat95").textContent = (state.metrics?.tick_to_order_ms_p95 ?? '-') ;
    $("#err").textContent = (state.metrics?.venue_error_rate_pct ?? 0).toFixed(2);
    const brk = state.metrics?.breaker || {};
    const breakerStatus = (brk.equity||brk.venue)?'<span class="badge err">TRIPPED</span>':'<span class="badge ok">OK</span>';
    $("#brk").innerHTML = breakerStatus;

    weightsDiv.innerHTML = '';
    for (const [k,v] of Object.entries(state.strategies||{})){
      const div = document.createElement('div');
      div.style.marginBottom = '6px';
      const enabledBadge = v.enabled===false?'<span class="badge warn">off</span>':'<span class="badge ok">on</span>';
      const share = typeof v.risk_share === 'number' ? (v.risk_share*100).toFixed(0) : '-';
      const pnlValue = Number((state.pnl_by_strategy || {})[k] ?? 0);
      const pnlBadgeClass = Number.isFinite(pnlValue) && pnlValue >= 0 ? 'ok' : 'err';
      const pnlText = Number.isFinite(pnlValue) ? `${pnlValue >= 0 ? '+' : ''}${pnlValue.toFixed(2)} $` : '-';
      div.innerHTML = `<b>${k}</b> ${enabledBadge} — risk ${share}% <span class="badge ${pnlBadgeClass}" style="margin-left:6px;">${pnlText}</span>`;
      weightsDiv.appendChild(div);
    }

    topsTBody.innerHTML = '';
    (state.top_symbols||[]).slice(0,30).forEach(s=>{
      const tr = document.createElement('tr');
      const velocity = typeof s.velocity === 'number' ? (s.velocity*100).toFixed(1)+'%' : '-';
      const eventHeat = typeof s.event_heat === 'number' ? (s.event_heat*100).toFixed(0)+'%' : '-';
      tr.innerHTML = `<td>${s.symbol}</td><td>${s.score?.toFixed?.(2) ?? '-'}</td><td>${velocity}</td><td>${eventHeat}</td>`;
      topsTBody.appendChild(tr);
    });
  }

  function merge(obj, update){
    return Object.assign({}, obj || {}, update || {});
  }

  ws.onmessage = (ev)=>{
    try{
      const msg = JSON.parse(ev.data);
      switch(msg.type){
        case 'snapshot': {
          const {type, ...rest} = msg;
          Object.assign(state, rest);
          break;
        }
        case 'mode':
          state.mode = msg.mode;
          break;
        case 'kill':
          state.kill = !!msg.enabled;
          break;
        case 'weights':
        case 'strategy': {
          const {type, strategy, ...rest} = msg;
          if (!state.strategies) state.strategies = {};
          state.strategies[strategy] = merge(state.strategies[strategy], rest);
          break;
        }
        case 'metrics':
          state.metrics = merge(state.metrics, msg.metrics);
          if (msg.pnl_by_strategy) state.pnl_by_strategy = {...msg.pnl_by_strategy};
          break;
        case 'top':
          state.top_symbols = Array.isArray(msg.symbols)?msg.symbols:[];
          break;
        case 'universe_weights': {
          const {type, ...rest} = msg;
          state.universe_weights = merge(state.universe_weights, rest);
          break;
        }
        case 'trade':
          // trades currently update latency metrics via separate metrics push; nothing else required.
          break;
        default:
          break;
      }
      render();
    }catch(e){console.error(e)}
  };
})();
