(function(){
  const $ = (sel)=>document.querySelector(sel);
  const deckToken = window.DECK_TOKEN || '';
  const jsonHeaders = ()=> {
    const headers = {'Content-Type':'application/json'};
    if (deckToken) headers['X-Deck-Token'] = deckToken;
    return headers;
  };
  const authHeaders = ()=> {
    const headers = {};
    if (deckToken) headers['X-Deck-Token'] = deckToken;
    return headers;
  };
  const ws = new WebSocket((location.protocol==='https:'?'wss://':'ws://') + location.host + '/ws');
  const weightsDiv = $("#weights");
  const topsTBody = $("#tops tbody");
  const transfersBody = $("#xfer_log tbody");
  const xferFrom = $("#xfer_from");
  const xferTo = $("#xfer_to");
  const xferAsset = $("#xfer_asset");
  const xferAmount = $("#xfer_amt");
  const xferSymbol = $("#xfer_symbol");
  const xferGo = $("#xfer_go");
  const state = {
    mode: 'yellow',
    kill: false,
    strategies: {},
    metrics: {},
    top_symbols: [],
    pnl_by_strategy: {},
    transfers: []
  };

  $("#mode").addEventListener("change", async (e)=>{
    await fetch('/risk/mode',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({mode:e.target.value})});
  });
  $("#killswitch").addEventListener("click", async ()=>{
    const curr = $("#killswitch").dataset.state==='on';
    const next = !curr;
    await fetch('/kill',{method:'POST',headers:jsonHeaders(),body:JSON.stringify({enabled:next})});
    setKill(next);
  });

  function setKill(on){
    $("#killswitch").dataset.state = on?'on':'off';
   $("#killswitch").textContent = on?'KILL ON':'KILL OFF';
    $("#killswitch").classList.toggle('danger', on);
  }

  function renderTransfers(){
    if (!transfersBody) return;
    transfersBody.innerHTML = '';
    const entries = Array.isArray(state.transfers) ? state.transfers : [];
    entries.forEach((xfer)=>{
      const tr = document.createElement('tr');
      const ts = typeof xfer.ts === 'number' ? new Date(xfer.ts * 1000).toLocaleTimeString() : '-';
      const resultText = (()=> {
        try {
          const raw = JSON.stringify(xfer.result ?? {});
          if (raw.length > 120) return raw.slice(0,117) + '...';
          return raw;
        } catch (err) {
          return String(xfer.result ?? '');
        }
      })();
      tr.innerHTML = `<td>${ts}</td><td>${xfer.type ?? ''}</td><td>${xfer.asset ?? ''}</td><td>${Number(xfer.amount ?? 0).toFixed(4)}</td><td>${xfer.symbol ?? ''}</td><td>${resultText}</td>`;
      transfersBody.appendChild(tr);
    });
  }

  function toggleIsolatedVisibility(){
    if (!xferFrom || !xferTo || !xferSymbol) return;
    const source = xferFrom.value || '';
    const target = xferTo.value || '';
    const needsSymbol = source.includes('ISOLATEDMARGIN') || target.includes('ISOLATEDMARGIN');
    $("#lbl_sym").style.display = needsSymbol ? 'inline-block' : 'none';
    xferSymbol.style.display = needsSymbol ? 'inline-block' : 'none';
  }

  async function doTransfer(fromWallet, toWallet, asset, amount, symbol){
    const parsedAmount = Number.parseFloat(amount);
    if (!Number.isFinite(parsedAmount) || parsedAmount <= 0){
      alert('Enter a positive amount to transfer.');
      return;
    }
    const body = {
      from_wallet: fromWallet,
      to_wallet: toWallet,
      asset: asset || 'USDT',
      amount: parsedAmount
    };
    if (symbol) body.symbol = symbol;
    try{
      const res = await fetch('/transfer',{
        method:'POST',
        headers:jsonHeaders(),
        body:JSON.stringify(body)
      });
      if (!res.ok){
        const txt = await res.text();
        throw new Error(txt || `status ${res.status}`);
      }
      alert('Transfer submitted.');
    }catch(err){
      console.error('transfer failed', err);
      alert(`Transfer failed: ${err.message || err}`);
    }
  }

  async function initTransfers(){
    if (!xferFrom || !xferTo) return;
    const setWalletOptions = (wallets)=>{
      xferFrom.innerHTML = wallets.map((w)=>`<option>${w}</option>`).join('');
      xferTo.innerHTML = wallets.map((w)=>`<option>${w}</option>`).join('');
    };
    const fallbackWallets = ['FUNDING','MAIN','UMFUTURE'];
    setWalletOptions(fallbackWallets);
    try{
      const res = await fetch('/transfer/types',{headers:authHeaders()});
      if (res.ok){
        const data = await res.json();
        const wallets = Array.isArray(data.wallets) && data.wallets.length ? data.wallets : fallbackWallets;
        setWalletOptions(wallets);
      }
    }catch(err){
      console.warn('transfer types fetch failed', err);
    }
    toggleIsolatedVisibility();
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
    renderTransfers();
  }

  if (xferFrom && xferTo){
    xferFrom.addEventListener('change', toggleIsolatedVisibility);
    xferTo.addEventListener('change', toggleIsolatedVisibility);
  }
  if (xferGo && xferFrom && xferTo && xferAsset && xferAmount){
    xferGo.addEventListener('click', ()=>{
      const symbol = xferSymbol && xferSymbol.style.display !== 'none' ? (xferSymbol.value || '').trim() : undefined;
      doTransfer(xferFrom.value, xferTo.value, xferAsset.value, xferAmount.value, symbol);
    });
  }
  document.querySelectorAll('button.mini[data-quick]').forEach((btn)=>{
    btn.addEventListener('click', ()=>{
      const parts = btn.dataset.quick?.split('->') || [];
      if (parts.length === 2 && xferFrom && xferTo){
        xferFrom.value = parts[0];
        xferTo.value = parts[1];
        toggleIsolatedVisibility();
      }
    });
  });
  initTransfers();

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
          state.transfers = Array.isArray(rest.transfers) ? rest.transfers.slice(0, 20) : [];
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
        case 'transfer': {
          if (!Array.isArray(state.transfers)) state.transfers = [];
          state.transfers.unshift(msg.transfer);
          if (state.transfers.length > 20) state.transfers.length = 20;
          break;
        }
        default:
          break;
      }
      render();
    }catch(e){console.error(e)}
  };
})();
