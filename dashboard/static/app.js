async function getJSON(url){ const r = await fetch(url, {cache:'no-store'}); return r.json(); }
const pnlCtx = document.getElementById('pnlChart').getContext('2d');
const guardCtx = document.getElementById('guardChart').getContext('2d');
const stateCtx = document.getElementById('stateChart').getContext('2d');
const pnlChart = new Chart(pnlCtx, { type:'line', data:{labels:[], datasets:[{label:'PnL', data:[]}]}, options:{animation:false,responsive:true,scales:{x:{display:false}}} });
const guardChart = new Chart(guardCtx, { type:'bar', data:{labels:[], datasets:[{label:'Guardrails', data:[]}]}, options:{animation:false,responsive:true} });
const stateChart = new Chart(stateCtx, { type:'bar', data:{labels:[], datasets:[{label:'States', data:[]}]}, options:{animation:false,responsive:true} });

// WS live updates + polling fallback
let ws;
function startWS(){
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (ev)=> {
    const msg = JSON.parse(ev.data);
    document.getElementById('status').textContent = `ws live | trades:${msg.trades} latest state:${msg.state ?? '—'} conf:${msg.conf?.toFixed(2) ?? '—'}`;
  };
  ws.onclose = ()=> { document.getElementById('status').textContent = 'ws closed; falling back to polling'; setTimeout(startWS, 5000); };
}
startWS();

async function refresh(){
  const pnl = await getJSON('/api/pnl').catch(()=>({points:[]}));
  if(pnl.points){
    pnlChart.data.labels = pnl.points.map((p,i)=> p.day || i);
    pnlChart.data.datasets[0].data = pnl.points.map(p=> p.pnl ?? p.y ?? p.value ?? p.pnl);
    pnlChart.update();
  }
  const guards = await getJSON('/api/guardrails').catch(()=>({counts:{}}));
  const gKeys = Object.keys(guards.counts || {});
  guardChart.data.labels = gKeys;
  guardChart.data.datasets[0].data = gKeys.map(k=> guards.counts[k]);
  guardChart.update();
  const st = await getJSON('/api/states').catch(()=>({hist:{}}));
  const sKeys = Object.keys(st.hist || {});
  stateChart.data.labels = sKeys;
  stateChart.data.datasets[0].data = sKeys.map(k=> st.hist[k]);
  stateChart.update();
  const latest = st.latest ? `state ${st.latest.state} (conf ${st.latest.conf.toFixed(2)})` : '—';
  document.getElementById('latestState').textContent = latest;
}
setInterval(refresh, 3000);
refresh();
