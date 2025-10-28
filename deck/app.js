(function(){
  const $ = (sel)=>document.querySelector(sel);
  const ws = new WebSocket((location.protocol==='https:'?'wss://':'ws://') + location.host + '/ws');
  const weightsDiv = $("#weights");
  const topsTBody = $("#tops tbody");

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

  function render(state){
    $("#mode").value = state.mode || 'yellow';
    setKill(!!state.kill);
    $("#equity").textContent = 'Equity: $' + (state.metrics?.equity_usd?.toFixed?.(2) ?? '-');
    $("#pnl24").textContent = 'PnL 24h: $' + (state.metrics?.pnl_24h?.toFixed?.(2) ?? '-');
    $("#dd").textContent = 'Drawdown: ' + ((state.metrics?.drawdown_pct??0)*100).toFixed(2) + '%';
    $("#riskuse").textContent = 'Open Risk: ' + ((state.metrics?.open_risk_sum_pct??0)*100).toFixed(2) + '%';
    $("#lat50").textContent = (state.metrics?.tick_to_order_ms_p50 ?? '-') ;
    $("#lat95").textContent = (state.metrics?.tick_to_order_ms_p95 ?? '-') ;
    $("#err").textContent = (state.metrics?.venue_error_rate_pct ?? 0).toFixed(2);
    const brk = state.metrics?.breaker || {};
    $("#brk").innerHTML = (brk.equity||brk.venue)?'<span class="badge err">TRIPPED</span>':'<span class="badge ok">OK</span>';

    weightsDiv.innerHTML = '';
    for (const [k,v] of Object.entries(state.strategies||{})){
      const div = document.createElement('div');
      div.style.marginBottom = '6px';
      div.innerHTML = `<b>${k}</b> — risk_share ${(v.risk_share*100).toFixed(0)}%`;
      weightsDiv.appendChild(div);
    }

    topsTBody.innerHTML = '';
    (state.top_symbols||[]).slice(0,30).forEach(s=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${s.symbol}</td><td>${s.score.toFixed(2)}</td><td>${(s.velocity*100).toFixed(1)}%</td><td>${(s.event_heat*100).toFixed(0)}%</td>`;
      topsTBody.appendChild(tr);
    });
  }

  ws.onmessage = (ev)=>{
    try{
      const msg = JSON.parse(ev.data);
      if (msg.type === 'snapshot'){
        render(msg);
      } else if (msg.type === 'mode'){
        $("#mode").value = msg.mode;
      } else if (msg.type === 'kill'){
        setKill(!!msg.enabled);
      }
    }catch(e){console.error(e)}
  };
})();