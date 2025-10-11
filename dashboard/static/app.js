// dashboard/static/app.v2.js
const OPS = (window.__DASH_CONFIG?.opsBase) || "http://127.0.0.1:8001";
const DASH = (window.__DASH_CONFIG?.dashBase) || "http://127.0.0.1:8002";

document.getElementById("endpoints").textContent = `Ops: ${OPS} • Dash: ${DASH}`;

function el(html){ const t=document.createElement("template"); t.innerHTML=html.trim(); return t.content.firstChild; }
function fmtUSD(x){ if(x==null||Number.isNaN(x)) return "—"; return x.toLocaleString(undefined,{style:"currency",currency:"USD",maximumFractionDigits:2}); }
function timeago(ts){ if(!ts) return ""; const d=new Date(ts).getTime(); const s=Math.max(0,(Date.now()-d)/1000); if(s<60) return `${Math.floor(s)}s`; const m=Math.floor(s/60); if(m<60) return `${m}m`; return `${Math.floor(m/60)}h`; }

async function getJSON(u, to=2500){ const c=new AbortController(); const id=setTimeout(()=>c.abort(),to); try{ const r=await fetch(u,{signal:c.signal}); if(!r.ok) throw new Error(r.status); return await r.json(); } finally{ clearTimeout(id); } }

function setLiveStrip(m){
  const root = document.getElementById("live-strip"); root.innerHTML="";
  const items = [
    ["Equity", fmtUSD(m.account_equity_usd)],
    ["Cash", fmtUSD(m.cash_usd)],
    ["Exposure", fmtUSD(m.gross_exposure_usd)],
    ["Realized PnL", fmtUSD(m.pnl_realized)],
    ["Unrealized", fmtUSD(m.pnl_unrealized)],
    ["Latency (ms)", Math.round(m.venue_latency_ms??0)]
  ];
  // Add optional warning style for over-leveraged positions (exposure > equity)
  const eq = m.account_equity_usd||0, ex = m.gross_exposure_usd||0;
  items.forEach(([k,v], i)=> {
    const div = el(`<div class="stat"><div class="label">${k}</div><div class="value">${v}</div></div>`);
    if (i === 2 && ex > eq && eq > 0) div.classList.add('warn'); // Exposure warning
    root.appendChild(div);
  });
}

function setPnL(m){
  const root = document.getElementById("pnl-stats"); root.innerHTML="";
  [["Realized", fmtUSD(m.pnl_realized)],["Unrealized", fmtUSD(m.pnl_unrealized)],["Drift", (m.drift_score??0).toFixed(2)]]
    .forEach(([k,v])=>root.appendChild(el(`<div class="stat"><div class="label">${k}</div><div class="value">${v}</div></div>`)));
  // spark (placeholder using drift as seed)
  const base = m.pnl_realized ?? 0, seed = Math.abs(Math.floor((m.drift_score ?? 0)*10));
  const series = Array.from({length:24},(_,i)=> base + Math.sin((i+seed)/3)*20 + i*0.5);
  const w=120,h=36, max=Math.max(...series,1), min=Math.min(...series,0); const step=w/Math.max(1,series.length-1);
  const norm = v => (h - ((v-min)/(max-min||1))*h);
  const d = series.map((v,i)=>`${i?'L':'M'}${i*step},${norm(v)}`).join(" ");
  document.getElementById("spark-path").setAttribute("d", d);
}

function setPolicy(m){
  const root = document.getElementById("policy-stats"); root.innerHTML="";
  [["Confidence", (m.policy_confidence??0).toFixed(2)],["Fill Ratio", (m.order_fill_ratio??0).toFixed(2)],["Latency (ms)", Math.round(m.venue_latency_ms??0)]]
    .forEach(([k,v])=>root.appendChild(el(`<div class="stat"><div class="label">${k}</div><div class="value">${v}</div></div>`)));
}

function pushFeed(listId, msg){
  const ul = document.getElementById(listId);
  ul.prepend(el(`<li><span>${msg.text}</span><span class="muted">${timeago(msg.ts)}</span></li>`));
  while(ul.children.length>12) ul.removeChild(ul.lastChild);
}

function wsConnect(topic, listId){
  const url = DASH.replace(/^http/,"ws") + `/ws/${topic}`;
  const pill = el(`<span class="pill">${topic} ○</span>`); document.getElementById("ws-indicators").appendChild(pill);
  let retry=600;
  const open = () => {
    const ws = new WebSocket(url);
    ws.onopen = () => { pill.textContent = `${topic} ●`; retry=600; };
    ws.onclose= () => { pill.textContent = `${topic} ○`; setTimeout(open, Math.min(retry*=2, 4000)); };
    ws.onmessage = e => {
      try{
        const j = JSON.parse(e.data);
        if(j.incident) pushFeed(listId, {text:`${j.incident} — ${j.reason||""}`, ts:j.ts});
        else if(j.action) pushFeed(listId, {text:`${j.action} — ${j.reason||""}`, ts:j.ts});
        else if(j.lineage||j.calibration){
          if(j.lineage){ document.getElementById("lineage").textContent = `Generations: ${j.lineage.count||0} • Latest: ${j.lineage.latest||"—"}`; }
          if(j.calibration){ setGallery(j.calibration.files||[]); }
        }
      }catch{}
    };
  };
  open();
}

function startGuardianWS(){
  const url = OPS.replace(/^http/,"ws") + '/ws/incidents';
  const pill = el(`<span class="pill">guardian ○</span>`);
  document.getElementById("ws-indicators").appendChild(pill);
  let retry=600;
  const open = () => {
    const ws = new WebSocket(url);
    ws.onopen = () => { pill.textContent = 'guardian ●'; retry=600; };
    ws.onclose= () => { pill.textContent = 'guardian ○'; setTimeout(open, Math.min(retry*=2, 4000)); };
    ws.onmessage = e => {
      try{
        const it = JSON.parse(e.data);
        const row = `<div class="row rowline"><div>${new Date(it.ts*1000).toLocaleTimeString()}</div><div>${it.level||'INFO'}</div><div>${it.msg||it.incident||'—'}</div></div>`;
        const box = document.getElementById('guardian-body');
        box.insertAdjacentHTML('afterbegin', row);
        // Keep only last N entries
        while(box.children.length>20) box.removeChild(box.lastChild);
      }catch{}
    };
  };
  open();
}

function setGallery(files){
  const root = document.getElementById("gallery"); root.innerHTML="";
  if(!files?.length){ root.appendChild(el(`<div class="muted">No calibration artifacts yet.</div>`)); return; }
  files.slice(-6).reverse().forEach(f => root.appendChild(el(`<div class="thumb">${f}</div>`)));
}

async function refreshPositions(){
  const res = await fetch('/api/account_snapshot').then(r=>r.json()).catch(()=>null);
  const el = document.getElementById('positions-body');
  if(!res){ el.textContent='—'; return; }
  const rows = (res.positions||[]).map(p=>`
    <div class="row rowline">
      <div>${p.symbol}</div><div>${p.qty_base.toFixed(8).replace(/\.?0+$/, '') || '0'}</div>
      <div>$${p.avg_price_quote.toFixed(2)}</div><div>$${p.last_price_quote.toFixed(2)}</div>
      <div>$${p.unrealized_usd.toFixed(2)}</div><div>$${p.realized_usd.toFixed(2)}</div>
    </div>`).join('');
  el.innerHTML = `
    <div class="row head"><div>Symbol</div><div>Qty</div><div>Avg</div><div>Last</div><div>UPL</div><div>RPL</div></div>
    ${rows || '<div class="muted">No positions</div>'}`;
}

async function refreshOnce(){
  try{
    const snap = await getJSON(`${DASH}/api/metrics_snapshot`);
    const m = snap?.metrics||{};
    setLiveStrip(m); setPnL(m); setPolicy(m);
    await refreshPositions();

    // T4: Apply color rules and show source badge
    const msgEl = document.getElementById("msg");

    // Apply color rules to the card
    const card = document.querySelector("#live-strip").parentElement;
    let cardClass = "";

    const drift = m.drift_score ?? 0;
    const conf = m.policy_confidence ?? 0;
    const latency = m.venue_latency_ms ?? 0;

    // Color rules: drift > 0.8 → red outline; confidence > 0.7 → green; latency > 200ms → amber
    if (drift > 0.8) cardClass = "bad-outline";
    else if (conf > 0.7) cardClass = "good-bg";
    else if (latency > 200) cardClass = "warn-bg";

    card.className = `card ${cardClass}`;

    // Show source badge
    if (snap?.source) {
      msgEl.textContent = `source: ${snap.source}`;
    } else {
      msgEl.textContent = "";
    }
  }catch(e){ document.getElementById("msg").textContent = "metrics unavailable"; }
  try{
    const lin = await getJSON(`${DASH}/api/lineage`);
    const idx = lin?.index; const latest = idx?.models?.length ? idx.models[idx.models.length-1]?.tag : "—";
    document.getElementById("lineage").textContent = `Generations: ${idx?.models?.length||0} • Latest: ${latest}`;
  }catch{}
  try{
    const gal = await getJSON(`${DASH}/api/artifacts/m15`);
    setGallery((gal?.files||[]).map(p => p.split("/").pop()));
  }catch{}
  // Fetch mode badge
  try{
    const meta = await getJSON(`${OPS}/meta`);
    if (meta?.mode) {
      const badgeEl = document.getElementById("mode-badge");
      badgeEl.textContent = `mode: ${meta.mode}`;
      badgeEl.className = `pill ${meta.mode === 'live' ? 'muted' : meta.mode === 'demo' ? 'ok' : 'muted'}`;
    }
  }catch(e){ /** silently fail */ }
}

async function ctrl(path, body){
  const msg = document.getElementById("msg");
  try{
    const headers = {'Content-Type':'application/json'};
    // T6: Add auth token for control actions
    if (window.__DASH_CONFIG?.token) {
      headers['X-OPS-TOKEN'] = window.__DASH_CONFIG.token;
    }
    const r = await fetch(`${OPS}/${path}`, {method:"POST", headers, body: body ? JSON.stringify(body) : undefined});
    msg.textContent = r.ok ? `${path} ok` : `${path} failed`;
  }catch(e){ msg.textContent = `${path} failed`; }
}

refreshOnce();
// Configurable polling interval (T1)
const pollMs = (window.__DASH_CONFIG?.pollMs) || 5000;
setInterval(refreshOnce, pollMs);
startGuardianWS();
wsConnect("scheduler","feed-scheduler");
wsConnect("lineage");  // heartbeat brings lineage/calibration
wsConnect("calibration");
window.ctrl = ctrl;
