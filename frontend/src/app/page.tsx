import React, { useEffect, useMemo, useRef, useState } from "react";

// --- Config: endpoints (override via window.__DASH_CONFIG or props) ---
const DEFAULT_CFG = {
  opsBase: "http://127.0.0.1:8001", // ops_api.py
  dashBase: "http://127.0.0.1:8002", // dashboard/app.py
};

// Utility: merge config from window
function useDashConfig() {
  const [cfg, setCfg] = useState(DEFAULT_CFG);
  useEffect(() => {
    const w: any = window as any;
    if (w.__DASH_CONFIG) setCfg({ ...DEFAULT_CFG, ...w.__DASH_CONFIG });
  }, []);
  return cfg;
}

// Utility: WS hook with auto-reconnect
function useWebSocket(url?: string) {
  const wsRef = useRef<WebSocket | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!url) return;
    let alive = true;
    let retry = 500;
    const connect = () => {
      try {
        const ws = new WebSocket(url);
        wsRef.current = ws;
        ws.onopen = () => {
          if (!alive) return; setConnected(true); retry = 500;
        };
        ws.onclose = () => {
          if (!alive) return; setConnected(false);
          setTimeout(connect, Math.min(retry *= 2, 4000));
        };
        ws.onerror = () => {
          try { ws.close(); } catch {}
        };
        ws.onmessage = (ev) => {
          try { const data = JSON.parse(ev.data); setMessages(m => [...m.slice(-199), data]); }
          catch { setMessages(m => [...m.slice(-199), ev.data]); }
        };
      } catch (e) {
        setTimeout(connect, Math.min(retry *= 2, 4000));
      }
    };
    connect();
    return () => { alive = false; try { wsRef.current?.close(); } catch {} };
  }, [url]);
  return { messages, connected };
}

// Fetcher with timeout + safe JSON
async function fetchJSON(url: string, timeoutMs = 2500) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return await res.json();
  } finally {
    clearTimeout(t);
  }
}

// Card shell
function Card({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl bg-neutral-900/70 border border-neutral-800 shadow-lg p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-neutral-100 font-semibold tracking-tight">{title}</h3>
        {right}
      </div>
      {children}
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="flex flex-col">
      <div className="text-sm text-neutral-400">{label}</div>
      <div className="text-lg md:text-xl font-semibold text-neutral-100 leading-tight">{value}</div>
      {sub && <div className="text-xs text-neutral-500">{sub}</div>}
    </div>
  );
}

// Sparkline (pure CSS SVG)
function Spark({ data, height = 36 }: { data: number[]; height?: number }) {
  const path = useMemo(() => {
    if (!data?.length) return "";
    const w = 120; const h = height; const max = Math.max(...data, 1); const min = Math.min(...data, 0);
    const norm = (v: number) => (h - ((v - min) / (max - min || 1)) * h);
    const step = w / Math.max(1, data.length - 1);
    return data.map((v, i) => `${i === 0 ? "M" : "L"}${i * step},${norm(v)}`).join(" ");
  }, [data, height]);
  return (
    <svg viewBox="0 0 120 36" className="w-full h-9">
      <path d={path} fill="none" stroke="currentColor" strokeWidth="2" className="text-neutral-300" />
    </svg>
  );
}

// Live Strip
function LiveStrip({ snapshot }: { snapshot: any }) {
  const items = [
    { label: "Realized PnL", value: formatUSD(snapshot?.pnl_realized) },
    { label: "Unrealized", value: formatUSD(snapshot?.pnl_unrealized) },
    { label: "Drift", value: (snapshot?.drift_score ?? 0).toFixed(2) },
    { label: "Policy Conf", value: (snapshot?.policy_confidence ?? 0).toFixed(2) },
    { label: "Fill Ratio", value: (snapshot?.order_fill_ratio ?? 0).toFixed(2) },
    { label: "Latency (ms)", value: Math.round(snapshot?.venue_latency_ms ?? 0) },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
      {items.map((s, i) => (
        <div key={i} className="rounded-xl bg-neutral-950/60 border border-neutral-800 p-3">
          <div className="text-xs text-neutral-400">{s.label}</div>
          <div className="text-lg font-semibold text-neutral-100">{s.value}</div>
        </div>
      ))}
    </div>
  );
}

// Guardian / Scheduler feeds
function Feed({ messages, empty }: { messages: any[]; empty: string }) {
  const arr = [...messages].reverse().slice(0, 12);
  if (!arr.length) return <div className="text-neutral-500 text-sm">{empty}</div>;
  return (
    <ul className="space-y-2">
      {arr.map((m, idx) => (
        <li key={idx} className="text-sm text-neutral-200 flex items-center justify-between">
          <span className="truncate mr-3">{summary(m)}</span>
          <span className="text-neutral-500 text-xs">{timeago(m?.ts)}</span>
        </li>
      ))}
    </ul>
  );
}

function summary(m: any) {
  if (!m) return "";
  if (m.incident) return `${m.incident} — ${m.reason ?? ""}`.trim();
  if (m.action) return `${m.action} — ${m.reason ?? ""}`.trim();
  if (m.lineage || m.calibration) return `lineage:${m?.lineage?.latest ?? "?"}  calibs:${m?.calibration?.files?.length ?? 0}`;
  try { return JSON.stringify(m); } catch { return String(m); }
}

function timeago(ts?: string) {
  if (!ts) return ""; const d = new Date(ts).getTime();
  const sec = Math.max(0, (Date.now() - d) / 1000);
  if (sec < 60) return `${Math.floor(sec)}s ago`;
  const min = Math.floor(sec / 60); if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60); return `${hr}h ago`;
}

function formatUSD(n?: number) {
  if (n == null || Number.isNaN(n)) return "—";
  const s = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(n as number);
  return s;
}

// Gallery thumbnails
function Gallery({ files, baseDir = "/" }: { files: string[]; baseDir?: string }) {
  if (!files?.length) return <div className="text-neutral-500 text-sm">No calibration artifacts yet.</div>;
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
      {files.map((f) => (
        <div key={f} className="rounded-xl overflow-hidden border border-neutral-800 bg-neutral-950">
          {/* We cannot guarantee file serving; show filename as badge */}
          <div className="p-3 text-xs text-neutral-300 border-b border-neutral-800">{f}</div>
          <div className="p-3 text-neutral-500 text-xs">(PNG preview served by backend)</div>
        </div>
      ))}
    </div>
  );
}

export default function DashboardV2() {
  const cfg = useDashConfig();
  const wsGuardian = useWebSocket(cfg?.dashBase ? cfg.dashBase.replace(/^http/, "ws") + "/ws/guardian" : undefined);
  const wsScheduler = useWebSocket(cfg?.dashBase ? cfg.dashBase.replace(/^http/, "ws") + "/ws/scheduler" : undefined);
  const wsLineage   = useWebSocket(cfg?.dashBase ? cfg.dashBase.replace(/^http/, "ws") + "/ws/lineage"   : undefined);
  const wsCalib     = useWebSocket(cfg?.dashBase ? cfg.dashBase.replace(/^http/, "ws") + "/ws/calibration": undefined);

  const [snapshot, setSnapshot] = useState<any>({});
  const [lineage, setLineage] = useState<any>({ count: 0, latest: "—" });
  const [calibs, setCalibs] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  // Poll metrics snapshot every 5s (degrades gracefully if offline)
  useEffect(() => {
    let alive = true; let t: any;
    const loop = async () => {
      try {
        const data = await fetchJSON(`${cfg.dashBase}/api/metrics_snapshot`);
        if (!alive) return; setSnapshot(data?.metrics ?? {});
      } catch {}
      t = setTimeout(loop, 5000);
    };
    loop();
    return () => { alive = false; clearTimeout(t); };
  }, [cfg.dashBase]);

  // Pull lineage & artifacts via REST once, then rely on WS heartbeat to stay fresh
  useEffect(() => {
    (async () => {
      try {
        const j = await fetchJSON(`${cfg.dashBase}/api/lineage`);
        const idx = j?.index; const latest = idx?.models?.length ? idx.models[idx.models.length - 1]?.tag : "—";
        setLineage({ count: idx?.models?.length ?? 0, latest });
      } catch {}
      try {
        const j2 = await fetchJSON(`${cfg.dashBase}/api/artifacts/m15`);
        setCalibs(j2?.files?.map((p: string) => p.split("/").pop()) ?? []);
      } catch {}
    })();
  }, [cfg.dashBase]);

  // WS: lineage + calibration updates
  useEffect(() => {
    const latestLine = wsLineage.messages.at(-1);
    if (latestLine?.lineage) setLineage({ count: latestLine.lineage.count ?? 0, latest: latestLine.lineage.latest ?? "—" });
    const latestCal = wsCalib.messages.at(-1);
    if (latestCal?.calibration?.files) setCalibs(latestCal.calibration.files);
  }, [wsLineage.messages, wsCalib.messages]);

  // Derived pnl series demo (placeholder spark)
  const pnlSeries = useMemo(() => {
    const base = snapshot?.pnl_realized ?? 0; // not actual series; placeholder
    const seed = Math.abs(Math.floor((snapshot?.drift_score ?? 0) * 10));
    return Array.from({ length: 24 }, (_, i) => base + Math.sin((i + seed) / 3) * 20 + i * 0.5);
  }, [snapshot]);

  async function trigger(action: string, body?: any) {
    try {
      setLoading(true); setMessage(null);
      await fetch(`${cfg.opsBase}/${action}`, {
        method: "POST",
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined
      });
      setMessage(`${action} ok`);
    } catch (e: any) {
      setMessage(`${action} failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen w-full bg-neutral-950 text-neutral-100">
      <div className="max-w-7xl mx-auto px-4 py-6 md:py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight">HMM Command Center v2</h1>
            <p className="text-neutral-400 text-sm">Live Ops • Metrics • Lineage • Guardrails</p>
          </div>
          <div className="flex items-center gap-2 text-xs text-neutral-400">
            <span className={`px-2 py-1 rounded-full border ${wsScheduler.connected ? "border-emerald-500 text-emerald-400" : "border-neutral-700"}`}>scheduler {wsScheduler.connected ? "●" : "○"}</span>
            <span className={`px-2 py-1 rounded-full border ${wsGuardian.connected ? "border-emerald-500 text-emerald-400" : "border-neutral-700"}`}>guardian {wsGuardian.connected ? "●" : "○"}</span>
            <span className={`px-2 py-1 rounded-full border ${wsLineage.connected   ? "border-emerald-500 text-emerald-400" : "border-neutral-700"}`}>lineage {wsLineage.connected ? "●" : "○"}</span>
            <span className={`px-2 py-1 rounded-full border ${wsCalib.connected     ? "border-emerald-500 text-emerald-400" : "border-neutral-700"}`}>calibration {wsCalib.connected ? "●" : "○"}</span>
          </div>
        </div>

        {/* Live strip */}
        <Card title="Live Strip">
          <LiveStrip snapshot={snapshot} />
        </Card>

        {/* Control Bar */}
        <div className="flex flex-wrap gap-3 mb-4">
          <button disabled={loading} onClick={() => trigger('kill')} className="px-3 py-1.5 bg-red-600/80 hover:bg-red-600 rounded-md text-sm">Kill</button>
          <button disabled={loading} onClick={() => trigger('retrain')} className="px-3 py-1.5 bg-blue-600/80 hover:bg-blue-600 rounded-md text-sm">Retrain</button>
          <button disabled={loading} onClick={() => trigger('canary_promote', { target_tag: 'latest' })} className="px-3 py-1.5 bg-emerald-600/80 hover:bg-emerald-600 rounded-md text-sm">Promote</button>
          {message && <span className="text-sm text-neutral-400">{message}</span>}
        </div>

        {/* Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
          <Card title="PnL & Exposure" right={<span className="text-neutral-400 text-xs">demo spark</span>}>
            <div className="grid grid-cols-3 gap-4">
              <Stat label="Realized" value={formatUSD(snapshot?.pnl_realized)} />
              <Stat label="Unrealized" value={formatUSD(snapshot?.pnl_unrealized)} />
              <Stat label="Drift" value={(snapshot?.drift_score ?? 0).toFixed(2)} />
            </div>
            <div className="mt-2"><Spark data={pnlSeries} /></div>
          </Card>

          <Card title="Policy Confidence">
            <div className="grid grid-cols-3 gap-4">
              <Stat label="Confidence" value={(snapshot?.policy_confidence ?? 0).toFixed(2)} />
              <Stat label="Fill Ratio" value={(snapshot?.order_fill_ratio ?? 0).toFixed(2)} />
              <Stat label="Latency (ms)" value={Math.round(snapshot?.venue_latency_ms ?? 0)} />
            </div>
            <div className="text-xs text-neutral-500 mt-2">Updated every 5s</div>
          </Card>

          <Card title="Scheduler (M19)">
            <Feed messages={wsScheduler.messages} empty="No scheduled actions yet." />
          </Card>

          <Card title="Guardian (M20)">
            <Feed messages={wsGuardian.messages} empty="No incidents reported." />
          </Card>

          <Card title="Lineage (M21)">
            <div className="grid grid-cols-2 gap-4">
              <Stat label="Generations" value={lineage?.count ?? 0} />
              <Stat label="Latest Tag" value={lineage?.latest ?? "—"} />
            </div>
            <div className="text-xs text-neutral-500 mt-2">Updates via WS heartbeat + REST fallback</div>
          </Card>

          <Card title="Calibration Gallery (M15)">
            <Gallery files={calibs} />
          </Card>
        </div>

        {/* Footer */}
        <div className="mt-8 text-center text-xs text-neutral-500">
          Ops: {cfg.opsBase} • Dash: {cfg.dashBase}
        </div>
      </div>
    </div>
  );
};
