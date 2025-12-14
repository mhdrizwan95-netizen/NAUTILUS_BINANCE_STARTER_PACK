import React, { useState, useEffect, useRef } from 'react';
import {
  Activity,
  AlertTriangle,
  Anchor,
  ArrowUpRight,
  BarChart2,
  Battery,
  Box,
  Brain,
  ChevronRight,
  Clock,
  Copy,
  Cpu,
  Database,
  DollarSign,
  Download,
  Filter,
  GitBranch,
  HardDrive,
  Layers,
  LayoutDashboard,
  PauseCircle,
  Play,
  PlayCircle,
  Power,
  RefreshCw,
  RotateCcw,
  Save,
  Server,
  Settings,
  ShieldAlert,
  Terminal,
  Wallet,
  Zap,
  Wifi,
  TrendingUp,
  X,
  XCircle,
  List,
  Sliders,
  MessageSquare,
  Send,
  Loader2,
  Sparkles
} from 'lucide-react';

// --- Types ---

interface Strategy {
  name: string;
  status: string;
  pnl: string;
  chartData: number[];
  color: string;
}

interface Order {
  time: string;
  symbol: string;
  type: string;
  price: string;
  size: string;
  status: string;
}

interface Feature {
  label: string;
  value: number;
  amount: string;
  color: string;
}

interface SystemStatus {
  label: string;
  status: string;
  color: string;
}

// --- Gemini API Integration ---

// --- Gemini API Integration ---
// [SECURE] Proxied via Ops API to keep keys server-side
const generateGeminiResponse = async (prompt: string): Promise<string> => {
  try {
    const response = await fetch("/api/ai/generate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ prompt }),
    });

    if (!response.ok) {
      if (response.status === 503) {
        return "AI Service Unavailable (Key not configured on server).";
      }
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    return data.candidates?.[0]?.content?.parts?.[0]?.text || "No response generated.";
  } catch (error) {
    console.error("Gemini Proxy Error:", error);
    return "Error connecting to Nautilus AI service.";
  }
};

// --- Shared UI Components ---

const ScanlineOverlay = () => (
  <div className="pointer-events-none fixed inset-0 z-[100] overflow-hidden opacity-[0.03]">
    <div className="h-full w-full bg-[linear-gradient(to_bottom,transparent_50%,black_50%)] bg-[length:100%_4px]" />
  </div>
);

const Card = ({ children, className = "", title, action, noPadding = false }: any) => (
  <div className={`bg-slate-900/60 border border-slate-800 rounded-xl backdrop-blur-md flex flex-col shadow-xl shadow-black/20 ${className} ${noPadding ? '!p-0' : '!p-4'}`}>
    {(title || action) && (
      <div className={`flex justify-between items-center !mb-3 ${noPadding ? '!p-4 !pb-0' : ''}`}>
        {title && <h3 className="!text-slate-400 !text-xs !font-bold uppercase !tracking-widest flex items-center !gap-2">{title}</h3>}
        {action && <div>{action}</div>}
      </div>
    )}
    {children}
  </div>
);

const StatValue = ({ label, value, subValue, type = "neutral" }: any) => {
  const colors: any = {
    positive: "!text-emerald-400",
    negative: "!text-rose-400",
    warning: "!text-amber-400",
    neutral: "!text-slate-100",
    brand: "!text-cyan-400",
    purple: "!text-purple-400"
  };

  return (
    <div className="flex flex-col items-center !text-center">
      <span className="!text-slate-500 !text-[10px] !font-bold uppercase !tracking-wider !mb-1">{label}</span>
      <div className="flex items-baseline !gap-2">
        <span className={`!text-xl !font-mono !font-bold ${colors[type] || colors.neutral}`}>{value}</span>
        {subValue && <span className="!text-xs !text-slate-500 !font-mono">{subValue}</span>}
      </div>
    </div>
  );
};

const TabButton = ({ active, icon: Icon, label, onClick }: any) => (
  <button
    onClick={onClick}
    className={`
      flex items-center !gap-2 !px-5 !py-3 !text-base !font-medium rounded-lg transition-all duration-200 border
      ${active
        ? "bg-cyan-500/10 border-cyan-500/50 !text-cyan-400 shadow-[0_0_15px_rgba(34,211,238,0.15)]"
        : "bg-transparent border-transparent !text-slate-400 hover:!text-slate-200 hover:bg-slate-800/50 hover:border-slate-700"}
    `}
  >
    <Icon size={18} />
    {label}
  </button>
);

const ProgressBar = ({ label, value, color = "bg-cyan-500" }: any) => (
  <div className="space-y-1.5">
    <div className="flex justify-between !text-xs">
      <span className="!text-slate-400 !font-medium">{label}</span>
      <span className="!text-slate-200 !font-mono">{value}%</span>
    </div>
    <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
      <div className={`h-full ${color} transition-all duration-500`} style={{ width: `${value}%` }} />
    </div>
  </div>
);

const MiniChart = ({ color = "#22d3ee", data = [] }: any) => (
  <div className="h-10 w-24 relative opacity-80">
    <svg className="w-full h-full overflow-visible" preserveAspectRatio="none">
      <path
        d={`M0,${30 - data[0]} L10,${30 - data[1]} L20,${30 - data[2]} L30,${30 - data[3]} L40,${30 - data[4]} L50,${30 - data[5]}`}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  </div>
);

const ApiGauge = ({ label, value, max = 100, unit = "ms" }: any) => {
  const percentage = Math.min((value / max) * 100, 100);
  const color = value < 50 ? "!text-emerald-400" : value < 150 ? "!text-amber-400" : "!text-rose-400";
  const strokeColor = value < 50 ? "#34d399" : value < 150 ? "#fbbf24" : "#fb7185";

  return (
    <div className="flex flex-col items-center justify-center !p-3 bg-slate-900/50 rounded-lg border border-slate-800 shadow-sm">
      <div className="relative w-16 h-16 flex items-center justify-center !mb-2">
        <svg className="w-full h-full transform -rotate-90">
          <circle cx="32" cy="32" r="28" stroke="#1e293b" strokeWidth="4" fill="transparent" />
          <circle cx="32" cy="32" r="28" stroke={strokeColor} strokeWidth="4" fill="transparent" strokeDasharray={175.93} strokeDashoffset={175.93 - (175.93 * percentage) / 100} className="transition-all duration-1000 ease-out" />
        </svg>
        <div className={`absolute inset-0 flex items-center justify-center !font-mono !text-sm !font-bold ${color}`}>
          {value}
        </div>
      </div>
      <span className="!text-[10px] !font-bold !text-slate-500 uppercase !tracking-wider">{label}</span>
    </div>
  );
};

const HeatmapCell = ({ label, value, change }: any) => {
  const isPositive = change >= 0;
  const bgClass = isPositive ? "bg-emerald-500/10 hover:bg-emerald-500/20" : "bg-rose-500/10 hover:bg-rose-500/20";
  const textClass = isPositive ? "!text-emerald-400" : "!text-rose-400";

  return (
    <div className={`${bgClass} p-2.5 rounded border border-slate-800/50 transition-colors cursor-pointer flex flex-col items-center justify-center !text-center`}>
      <div className="flex items-center !gap-1 !mb-1">
        <span className="!text-xs !font-bold !text-slate-200">{label}</span>
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="!text-sm !font-mono !text-slate-300">{value}</span>
        <span className={`!text-[10px] !font-mono ${textClass}`}>{change > 0 ? '+' : ''}{change}%</span>
      </div>
    </div>
  );
};

const Toast = ({ message, detail, type = "error" }: any) => (
  <div className={`fixed bottom-6 right-6 z-50 flex items-start !gap-3 !p-3 rounded-lg shadow-2xl border backdrop-blur-md max-w-sm animate-in slide-in-from-right duration-300 ${type === 'error' ? 'bg-rose-950/90 border-rose-500/50 !text-rose-200' : 'bg-slate-900/90 border-slate-700 !text-slate-200'}`}>
    <div className={`p-1.5 rounded-full ${type === 'error' ? 'bg-rose-500/20 !text-rose-400' : 'bg-slate-700 !text-slate-400'}`}>
      <AlertTriangle size={16} />
    </div>
    <div>
      <h4 className="!text-sm !font-bold mb-0.5">{message}</h4>
      {detail && <p className="!text-[10px] !font-mono opacity-80 break-all">{detail}</p>}
    </div>
    <button className="!text-slate-400 hover:!text-white transition-colors"><X size={14} /></button>
  </div>
);

const FlagItem = ({ title, description, status, value }: any) => (
  <div className="flex items-center justify-between p-2.5 rounded bg-slate-950/50 border border-slate-800">
    <div>
      <div className="!text-xs !font-bold !text-slate-300 mb-0.5">{title}</div>
      <div className="!text-[10px] !text-slate-500">{description}</div>
    </div>
    <div className="!text-right">
      {status && <div className={`!text-[10px] !font-bold !px-2 py-0.5 rounded ${status === 'ENABLED' ? 'bg-emerald-500/10 !text-emerald-400 border border-emerald-500/20' : 'bg-slate-800 !text-slate-500 border border-slate-700'}`}>{status}</div>}
      {value && <div className="!font-mono !text-xs !text-cyan-400">{value}</div>}
    </div>
  </div>
);

// --- AI Components ---

const AIAssistant = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([
    { role: 'assistant', text: 'Hello Operator. How can I assist with your trading strategy today?' }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isOpen]);

  const handleSend = async () => {
    if (!input.trim()) return;

    const userMessage = { role: 'user', text: input };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    const systemContext = `
      You are Nautilus, an advanced AI trading assistant integrated into a high-frequency trading terminal.
      Current Market Context: BTC/USDT is ranging, Volatility is low.
      Active Strategies: HMM_Trend_v2 (Active), MeanRev_Scalp (Active).
      System Status: Healthy.
      User Query: ${input}
    `;

    const responseText = await generateGeminiResponse(systemContext);

    setMessages(prev => [...prev, { role: 'assistant', text: responseText }]);
    setIsLoading(false);
  };

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end">
      {isOpen && (
        <div className="!mb-4 w-80 md:w-96 bg-slate-900/95 backdrop-blur-xl border border-slate-700 rounded-xl shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-bottom-10 duration-300">
          <div className="!p-3 border-b border-slate-700 flex justify-between items-center bg-slate-800/50">
            <div className="flex items-center !gap-2">
              <Sparkles size={16} className="!text-cyan-400" />
              <span className="!text-xs !font-bold !text-slate-200 uppercase !tracking-wider">Nautilus AI</span>
            </div>
            <button onClick={() => setIsOpen(false)} className="!text-slate-400 hover:!text-white"><XCircle size={16} /></button>
          </div>
          <div className="h-80 overflow-y-auto !p-4 !space-y-4 scrollbar-thin scrollbar-thumb-slate-700">
            {messages.map((msg, idx) => (
              <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] !p-3 rounded-lg !text-xs ${msg.role === 'user' ? 'bg-cyan-500/20 !text-cyan-100 border border-cyan-500/30 rounded-br-none' : 'bg-slate-800 !text-slate-300 border border-slate-700 rounded-bl-none'}`}>
                  {msg.text}
                </div>
              </div>
            ))}
            {isLoading && (
              <div className="flex justify-start">
                <div className="bg-slate-800 !p-3 rounded-lg rounded-bl-none border border-slate-700">
                  <Loader2 size={16} className="animate-spin !text-cyan-400" />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
          <div className="!p-3 border-t border-slate-700 bg-slate-800/30 flex !gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder="Ask Nautilus..."
              className="flex-1 bg-slate-900 border border-slate-700 rounded !px-3 !py-2 !text-xs !text-white focus:outline-none focus:border-cyan-500"
            />
            <button onClick={handleSend} disabled={isLoading} className="!p-2 bg-cyan-500/20 !text-cyan-400 rounded border border-cyan-500/50 hover:bg-cyan-500/30 disabled:opacity-50">
              <Send size={16} />
            </button>
          </div>
        </div>
      )}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`h-12 w-12 rounded-full flex items-center justify-center shadow-lg shadow-cyan-500/20 transition-all duration-300 ${isOpen ? 'bg-slate-800 !text-slate-400 rotate-90' : 'bg-gradient-to-br from-cyan-500 to-blue-600 !text-white hover:scale-110'}`}
      >
        {isOpen ? <XCircle size={24} /> : <MessageSquare size={24} />}
      </button>
    </div>
  );
};

// --- View Components ---

const DashboardView = ({ strategies, orderLog }: { strategies: Strategy[], orderLog: Order[] }) => (
  <div className="grid grid-cols-12 !gap-4 animate-in fade-in duration-500 h-[calc(100vh-140px)] min-h-[800px]">
    {/* Left Main Area (9 Columns) */}
    <div className="col-span-12 lg:col-span-9 flex flex-col !gap-4">

      {/* Top Row: Equity & Stats */}
      <div className="grid grid-cols-12 !gap-4 !h-auto lg:!h-56">
        {/* Net Equity Curve (6 Columns -> 50% of Main Area) */}
        <Card className="col-span-12 lg:col-span-6" title={<><BarChart2 size={16} /> Net Equity Curve</>}>
          <div className="flex items-end !gap-2 !mb-4">
            <span className="!text-3xl !font-mono !font-bold !text-white !tracking-tight">$68,458.20</span>
            <span className="!text-sm !font-mono !text-emerald-400 !mb-2 flex items-center !gap-1 !font-bold">
              <ArrowUpRight size={14} /> +3.4% (24h)
            </span>
          </div>
          <div className="flex-1 w-full relative min-h-0">
            <svg className="w-full h-full overflow-visible" preserveAspectRatio="none">
              <path d="M0,80 Q30,70 60,75 T120,60 T180,40 T240,50 T300,30 T360,20" fill="none" stroke="#22d3ee" strokeWidth="3" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
              <defs>
                <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.2" />
                  <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
                </linearGradient>
              </defs>
              <path d="M0,80 Q30,70 60,75 T120,60 T180,40 T240,50 T300,30 T360,20 L360,100 L0,100 Z" fill="url(#chartGrad)" stroke="none" />
            </svg>
          </div>
        </Card>

        {/* Stats Columns (3 Columns each -> 25% of Main Area) */}
        <Card className="col-span-6 lg:col-span-3 flex-col justify-center items-center !text-center border-amber-500/20 bg-amber-500/5">
          <div className="flex items-center !gap-3 !mb-2">
            <div className="!p-2 bg-amber-500/10 rounded !text-amber-400"><Wifi size={16} /></div>
            <span className="text-slate-500/70 !text-xs !font-bold uppercase">API Latency</span>
          </div>
          <div className="!text-4xl !font-mono !text-amber-400 !font-bold">32ms</div>
        </Card>

        <Card className="col-span-6 lg:col-span-3 flex-col justify-center items-center !text-center border-indigo-500/20 bg-indigo-500/5">
          <div className="flex items-center !gap-3 !mb-2">
            <div className="!p-2 bg-indigo-500/10 rounded !text-indigo-400"><Battery size={16} /></div>
            <span className="text-slate-500/70 !text-xs !font-bold uppercase">Margin Usage</span>
          </div>
          <div className="!text-4xl !font-mono !text-indigo-400 !font-bold">45%</div>
        </Card>
      </div>

      {/* Middle Row: Active Strategies */}
      <div className="h-40 flex flex-col !gap-2 !mt-8">
        <h3 className="!text-slate-400 !text-sm !font-bold uppercase !tracking-wider flex items-center !gap-2 !px-1">
          <Zap size={16} className="!text-cyan-400" /> Active Strategies
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 !gap-4 h-full">
          {strategies.map((strat, i) => (
            <Card key={i} className="relative overflow-hidden group hover:border-slate-600 transition-colors flex flex-col justify-between">
              <div className="flex justify-between items-start !mb-3">
                <span className="!font-mono !text-sm !font-bold !text-slate-200">{strat.name}</span>
                <div className={`w-2 h-2 rounded-full ${strat.status === 'active' ? 'bg-emerald-500 animate-pulse' : 'bg-slate-500'}`}></div>
              </div>
              <div className="flex justify-between items-end">
                <div>
                  <div className="!text-xs !text-slate-500 !mb-1">24h PnL</div>
                  <div className={`!font-mono !text-2xl !font-bold ${strat.pnl.startsWith('+') ? '!text-emerald-400' : '!text-slate-400'}`}>
                    {strat.pnl}
                  </div>
                </div>
                <MiniChart color={strat.color} data={strat.chartData} />
              </div>
            </Card>
          ))}
        </div>
      </div>

      {/* Bottom Row: System Status */}
      <Card className="bg-gradient-to-r from-emerald-950/30 to-slate-900 border-emerald-500/20 h-24 justify-center">
        <div className="flex items-center justify-between">
          <div className="flex items-center !gap-4">
            <div className="h-12 w-12 rounded-full bg-emerald-500/10 flex items-center justify-center border border-emerald-500/20 shadow-[0_0_10px_rgba(16,185,129,0.2)]">
              <Activity size={24} className="!text-emerald-500" />
            </div>
            <div>
              <div className="!text-white !font-bold !text-lg">System Status: ONLINE</div>
              <div className="!text-sm !text-slate-400">All execution engines operational</div>
            </div>
          </div>
          <div className="!text-right">
            <div className="!text-xs !text-slate-500 !mb-1">Liquidation Risk</div>
            <div className="!text-2xl !font-mono !text-emerald-400 !font-bold">Low (12%)</div>
          </div>
        </div>
      </Card>
    </div>

    {/* Right Sidebar: Live Order Feed (3 Columns) */}
    <div className="col-span-12 lg:col-span-3 h-full">
      <Card className="h-full flex flex-col" title={<><RefreshCw size={14} className="animate-spin-slow" /> Live Order Feed</>} noPadding>
        <div className="flex-1 overflow-y-auto scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent !p-0">
          <table className="w-full !text-left !text-xs !font-mono border-collapse table-fixed">
            <thead className="sticky top-0 bg-slate-900/95 backdrop-blur z-10 !text-slate-500 border-b border-slate-800">
              <tr>
                <th className="!py-3 !px-3 !font-medium w-[25%]">Time</th>
                <th className="!py-3 !px-3 !font-medium w-[25%]">Sym</th>
                <th className="!py-3 !px-3 !text-right !font-medium w-[25%]">Price</th>
                <th className="!py-3 !px-3 !text-right !font-medium w-[25%]">Side</th>
              </tr>
            </thead>
            <tbody>
              {orderLog.map((order, i) => (
                <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/50 transition-colors group">
                  <td className="!py-2 !px-3 !text-slate-500 truncate">{order.time}</td>
                  <td className="!py-2 !px-3 !font-bold !text-slate-300 truncate">{order.symbol}</td>
                  <td className="!py-2 !px-3 !text-right !text-slate-400 truncate">{order.price}</td>
                  <td className="!py-2 !px-3 !text-right">
                    <span className={`
                            px-1.5 py-0.5 rounded !text-[10px] !font-bold 
                            ${order.type === 'BUY' ? 'bg-emerald-500/10 !text-emerald-500 border border-emerald-500/20' : 'bg-rose-500/10 !text-rose-500 border border-rose-500/20'}
                         `}>
                      {order.type}
                    </span>
                  </td>
                </tr>
              ))}
              {[...Array(15)].map((_, i) => (
                <tr key={`fade-${i}`} className="opacity-20 blur-[1px]">
                  <td className="!py-2 !px-3 !text-slate-600">--:--:--</td>
                  <td className="!py-2 !px-3 !text-slate-600">---</td>
                  <td className="!py-2 !px-3 !text-slate-600 !text-right">---</td>
                  <td className="!py-2 !px-3 !text-right"><span className="!text-slate-700">---</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="!p-3 border-t border-slate-800 bg-slate-900/50 !text-center !text-[10px] !text-slate-500 uppercase !tracking-widest">
          Feed connected: WebSocket Secure
        </div>
      </Card>
    </div>
  </div>
);

const NeuralView = ({ featureImportance }: { featureImportance: Feature[] }) => {
  const [analysis, setAnalysis] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const generateAnalysis = async () => {
    setIsAnalyzing(true);
    const context = `
         Analyze the following market regime data for a crypto trading bot:
         Current Regime: BULL (probability 0.82)
         Model Accuracy (24h): 68.4%
         Feature Importance:
         - Order Book Imbalance: 0.85
         - Volatility Delta: 0.65
         - Funding Rate Predicted: 0.45
         
         Provide a concise, 2-sentence strategic recommendation for a high-frequency trading system.
      `;
    const result = await generateGeminiResponse(context);
    setAnalysis(result);
    setIsAnalyzing(false);
  };

  return (
    <div className="!space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="grid grid-cols-2 md:grid-cols-4 !gap-4">
        <Card className="flex-col items-center justify-center !text-center !py-3 border-indigo-500/20 bg-indigo-500/5">
          <div className="!p-2 !mb-2 rounded-lg bg-indigo-500/20 !text-indigo-400"><Brain size={20} /></div>
          <StatValue label="Model Version" value="v2.1.0-RC3" subValue="Canary" type="neutral" />
        </Card>
        <Card className="flex-col items-center justify-center !text-center !py-3 border-amber-500/20 bg-amber-500/5">
          <div className="!p-2 !mb-2 rounded-lg bg-amber-500/20 !text-amber-400"><Clock size={20} /></div>
          <StatValue label="Last Trained" value="4h 12m" subValue="ago" type="warning" />
        </Card>
        <Card className="flex-col items-center justify-center !text-center !py-3 border-emerald-500/20 bg-emerald-500/5">
          <div className="!p-2 !mb-2 rounded-lg bg-emerald-500/20 !text-emerald-400"><Activity size={20} /></div>
          <StatValue label="Accuracy (24H)" value="68.4%" subValue="+1.2%" type="positive" />
        </Card>
        <Card className="flex-col items-center justify-center !text-center !py-3 border-cyan-500/20 bg-cyan-500/5">
          <div className="!p-2 !mb-2 rounded-lg bg-cyan-500/20 !text-cyan-400"><Layers size={20} /></div>
          <StatValue label="Current Regime" value="BULL" subValue="p=0.82" type="positive" />
        </Card>
      </div>

      {/* AI Analysis Section */}
      <Card className="border-purple-500/30 bg-purple-500/5">
        <div className="flex justify-between items-start">
          <div>
            <h3 className="!text-purple-400 !text-xs !font-bold uppercase !tracking-widest flex items-center !gap-2 !mb-2">
              <Sparkles size={14} /> AI Regime Analysis
            </h3>
            <p className="!text-slate-300 !text-sm !leading-relaxed max-w-3xl">
              {analysis || "Click generate to analyze current market regime and feature weights using Gemini AI..."}
            </p>
          </div>
          <button
            onClick={generateAnalysis}
            disabled={isAnalyzing}
            className="flex items-center !gap-2 !px-4 !py-2 bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/50 rounded !text-purple-300 !text-xs !font-bold transition-all disabled:opacity-50"
          >
            {isAnalyzing ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            {isAnalyzing ? "Analyzing..." : "Generate Insight"}
          </button>
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-3 !gap-6">
        <Card className="lg:col-span-2 h-80" title={<><TrendingUp size={16} /> Market Regime Probability Stream</>}>
          <div className="w-full h-full flex flex-col justify-end relative">
            <div className="absolute inset-0 flex items-end justify-between !px-2 !gap-1 opacity-80">
              {[...Array(40)].map((_, i) => {
                const height = 20 + Math.random() * 60;
                let colorClass = "bg-slate-700";
                if (height > 60) colorClass = "bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.4)]";
                else if (height < 40) colorClass = "bg-rose-500 shadow-[0_0_10px_rgba(244,63,94,0.4)]";
                else colorClass = "bg-slate-500";
                return (
                  <div key={i} className="flex flex-col !gap-1 w-full items-center justify-end h-full group">
                    <div className={`w-full rounded-t-sm transition-all duration-300 hover:opacity-100 opacity-60 ${colorClass}`} style={{ height: `${height}%` }}></div>
                  </div>
                )
              })}
            </div>
            <div className="absolute top-2 left-2 flex !gap-4 !text-xs !font-mono bg-slate-900/80 !p-2 rounded border border-slate-800 backdrop-blur">
              <div className="flex items-center !gap-1"><div className="w-2 h-2 rounded-full bg-emerald-500"></div> BULL</div>
              <div className="flex items-center !gap-1"><div className="w-2 h-2 rounded-full bg-slate-500"></div> CRAB</div>
              <div className="flex items-center !gap-1"><div className="w-2 h-2 rounded-full bg-rose-500"></div> BEAR</div>
            </div>
          </div>
          <div className="border-t border-slate-800 !mt-2 !pt-2 flex justify-between !text-xs !text-slate-500 !font-mono">
            <span>10:00 UTC</span>
            <span>14:00 UTC</span>
          </div>
        </Card>

        <Card title={<><Database size={16} /> Feature Importance</>}>
          <div className="!space-y-4">
            {featureImportance.map((item, idx) => (
              <ProgressBar key={idx} label={item.label} value={item.value} color={item.color} />
            ))}
          </div>
        </Card>
      </div>

      <Card title={<><GitBranch size={16} /> Canary Model Performance vs Production</>}>
        <div className="h-64 w-full relative">
          <div className="absolute inset-0 grid grid-cols-6 grid-rows-4 !gap-4 pointer-events-none">
            {[...Array(24)].map((_, i) => <div key={i} className="border-r border-t border-slate-800/30 first:border-l last:border-b-0"></div>)}
          </div>
          <svg className="w-full h-full overflow-visible" preserveAspectRatio="none">
            <path d="M0,200 C50,190 100,180 150,150 C200,140 250,145 300,130 C350,120 400,110 450,100 C500,90 550,85 600,80" fill="none" stroke="#3b82f6" strokeWidth="2" strokeDasharray="5,5" vectorEffect="non-scaling-stroke" />
            <path d="M0,200 C50,180 100,160 150,140 C200,100 250,110 300,90 C350,70 400,60 450,40 C500,30 550,20 600,10" fill="url(#canaryGrad)" stroke="#a855f7" strokeWidth="3" vectorEffect="non-scaling-stroke" />
            <defs>
              <linearGradient id="canaryGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#a855f7" stopOpacity="0.2" />
                <stop offset="100%" stopColor="#a855f7" stopOpacity="0" />
              </linearGradient>
            </defs>
          </svg>
          <div className="absolute top-4 left-4 flex flex-col !gap-2 bg-slate-900/80 !p-3 rounded-lg border border-slate-800 backdrop-blur">
            <div className="flex items-center justify-between !gap-6 !text-xs">
              <span className="!text-slate-400 flex items-center !gap-2"><span className="w-3 h-0.5 bg-blue-500"></span> Production (v2.0)</span>
              <span className="!font-mono !text-blue-400">+12.5%</span>
            </div>
            <div className="flex items-center justify-between !gap-6 !text-xs">
              <span className="!text-slate-200 !font-bold flex items-center !gap-2"><span className="w-3 h-0.5 bg-purple-500"></span> Canary (v2.1-RC3)</span>
              <span className="!font-mono !text-purple-400 !font-bold">+18.2%</span>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
};

const SystemView = ({ systemStatus, systemLogs }: { systemStatus: SystemStatus[], systemLogs: string[] }) => (
  <div className="!space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
    <div className="grid grid-cols-2 md:grid-cols-4 !gap-4">
      {systemStatus.map((status, i) => (
        <div key={i} className="bg-slate-900/50 border border-slate-800 rounded-lg !p-3 flex flex-col items-center justify-center !text-center shadow-lg hover:border-slate-600 transition-colors">
          <span className="!text-[10px] !font-bold !text-slate-500 !tracking-widest uppercase !mb-1">{status.label}</span>
          <span className={`!font-mono !text-sm !font-bold ${status.color}`}>{status.status}</span>
        </div>
      ))}
    </div>

    <div className="grid grid-cols-1 lg:grid-cols-3 !gap-6">
      <ApiGauge label="API Weight (Binance)" value={464} max={1200} />

      <Card className="lg:col-span-2" title={<><Activity size={16} /> Order Latency Heatmap</>}>
        <div className="flex flex-col h-full">
          <div className="flex-1 grid grid-cols-[repeat(20,minmax(0,1fr))] !gap-1 !p-2 bg-slate-950/50 rounded border border-slate-800/50 min-h-[160px]">
            {[...Array(60)].map((_, i) => {
              const latency = Math.floor(Math.random() * 20) + Math.floor(Math.random() * 10) * (Math.random() > 0.9 ? 10 : 1);
              return <HeatmapCell key={i} latency={latency} />
            })}
          </div>
          <div className="flex justify-between items-center !mt-2 !px-2 !text-[10px] !text-slate-500 !font-mono uppercase !tracking-wider">
            <span className="flex items-center !gap-1"><div className="w-2 h-2 rounded-full bg-emerald-500"></div> Low (&lt;28ms)</span>
            <span className="flex items-center !gap-1"><div className="w-2 h-2 rounded-full bg-rose-500"></div> High (&gt;80ms)</span>
          </div>
        </div>
      </Card>
    </div>

    <div className="grid grid-cols-1 lg:grid-cols-2 !gap-6">
      <div className="!space-y-6">
        <div className="bg-emerald-950/20 border border-emerald-500/30 rounded-lg !p-3 flex items-center justify-center !gap-2 shadow-[0_0_15px_rgba(16,185,129,0.1)]">
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
          <span className="!text-emerald-400 !font-mono !text-xs !font-bold uppercase !tracking-wider">System Healthy • Tick Gap &lt; 1s</span>
        </div>
        <Card title={<><Server size={16} /> Docker Resources</>}>
          <ProgressBar value={12} label="CPU Usage" color="bg-cyan-500" />
          <ProgressBar value={30} label="RAM Usage" color="bg-indigo-500" />
        </Card>
        <Card title={<><HardDrive size={16} /> Database Health</>}>
          <div className="grid grid-cols-3 !gap-4">
            <div className="!text-center">
              <div className="!text-xs !text-slate-500 !mb-1">Disk Usage</div>
              <div className="!text-lg !font-mono !text-slate-200">40%</div>
              <div className="h-1 w-full bg-slate-800 rounded-full !mt-2"><div className="h-full bg-blue-500 w-[40%] rounded-full"></div></div>
            </div>
            <div className="!text-center">
              <div className="!text-xs !text-slate-500 !mb-1">Queue Size</div>
              <div className="!text-lg !font-mono !text-emerald-400">0</div>
              <div className="h-1 w-full bg-slate-800 rounded-full !mt-2"><div className="h-full bg-emerald-500 w-[0%] rounded-full"></div></div>
            </div>
            <div className="!text-center">
              <div className="!text-xs !text-slate-500 !mb-1">Write Latency</div>
              <div className="!text-lg !font-mono !text-slate-200">4ms</div>
              <div className="h-1 w-full bg-slate-800 rounded-full !mt-2"><div className="h-full bg-purple-500 w-[10%] rounded-full"></div></div>
            </div>
          </div>
        </Card>
      </div>
      <Card title={<><Terminal size={16} /> System Log Stream</>} className="h-full min-h-[300px]" noPadding>
        <div className="flex-1 bg-slate-950/80 !p-4 !font-mono !text-xs overflow-y-auto max-h-[350px] scrollbar-thin scrollbar-thumb-slate-800 rounded-b-xl">
          {systemLogs.map((log, i) => {
            const isWarn = log.includes("[WARN]");
            return (
              <div key={i} className={`mb-1.5 border-l-2 !pl-2 ${isWarn ? 'border-amber-500 !text-amber-200' : 'border-slate-800 !text-slate-400'}`}>
                <span className="opacity-50 !mr-2">{log.split(' ')[0]}</span>
                {log.substring(log.indexOf(' ') + 1)}
              </div>
            )
          })}
          <div className="animate-pulse !text-cyan-500 !mt-2">_</div>
        </div>
      </Card>
    </div>
  </div>
);

const StrategyView = ({ strategies }: { strategies: Strategy[] }) => {
  const [selectedStrategy, setSelectedStrategy] = useState(strategies[0]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 !gap-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* Sidebar List */}
      <div className="lg:col-span-4 !space-y-4">
        <Card title={<><List size={16} /> Available Strategies</>} className="h-full">
          <div className="!space-y-2">
            {strategies.map(strat => (
              <div
                key={strat.name}
                onClick={() => setSelectedStrategy(strat)}
                className={`!p-3 rounded-lg border cursor-pointer transition-all ${selectedStrategy.name === strat.name ? 'bg-cyan-500/10 border-cyan-500/50 ring-1 ring-cyan-500/20' : 'bg-slate-900/40 border-slate-800 hover:border-slate-600 hover:bg-slate-800'}`}
              >
                <div className="flex justify-between items-center !mb-2">
                  <span className={`!font-mono !font-bold ${selectedStrategy.name === strat.name ? '!text-cyan-400' : '!text-slate-200'}`}>{strat.name}</span>
                  <div className={`!px-2 py-0.5 rounded !text-[10px] !font-bold uppercase ${strat.status === 'active' ? 'bg-emerald-500/20 !text-emerald-400' : 'bg-slate-700 !text-slate-400'}`}>{strat.status}</div>
                </div>
                <div className="flex justify-between !text-xs !text-slate-500 !font-mono">
                  <span>PnL: <span className={strat.pnl.startsWith('+') ? '!text-emerald-400' : '!text-rose-400'}>{strat.pnl}</span></span>
                  <span>Alloc: {strat.name === 'HMM_Trend_v2' ? '45%' : strat.name === 'MeanRev_Scalp' ? '30%' : '10%'}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="!mt-4 !pt-4 border-t border-slate-800">
            <button className="w-full !py-2 rounded border border-dashed border-slate-700 !text-slate-500 hover:!text-slate-300 hover:border-slate-500 !text-xs !font-mono">+ Import Strategy</button>
          </div>
        </Card>
      </div>

      {/* Main Detail Area */}
      <div className="lg:col-span-8 !space-y-6">
        <Card title={<><Sliders size={16} /> Strategy Control: {selectedStrategy.name}</>}
          action={
            <div className="flex items-center !gap-2">
              <button className="!px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 !text-xs !text-slate-300 border border-slate-700 transition-colors">Edit Config</button>
              <button className={`!px-3 py-1.5 rounded !text-xs !font-bold border transition-colors ${selectedStrategy.status === 'active' ? 'bg-rose-500/10 !text-rose-500 border-rose-500/30 hover:bg-rose-500/20' : 'bg-emerald-500/10 !text-emerald-500 border-emerald-500/30 hover:bg-emerald-500/20'}`}>
                {selectedStrategy.status === 'active' ? 'Pause Execution' : 'Resume Execution'}
              </button>
            </div>
          }
        >
          <div className="grid grid-cols-3 !gap-4 !mb-6">
            <div className="!p-2 bg-slate-950/50 rounded border border-slate-800 flex flex-col items-center !text-center">
              <div className="!text-xs !text-slate-500 !mb-1">Total Trades</div>
              <div className="!text-xl !font-mono !text-slate-200">1,243</div>
            </div>
            <div className="!p-2 bg-slate-950/50 rounded border border-slate-800 flex flex-col items-center !text-center">
              <div className="!text-xs !text-slate-500 !mb-1">Win Rate</div>
              <div className="!text-xl !font-mono !text-emerald-400">64.2%</div>
            </div>
            <div className="!p-2 bg-slate-950/50 rounded border border-slate-800 flex flex-col items-center !text-center">
              <div className="!text-xs !text-slate-500 !mb-1">Profit Factor</div>
              <div className="!text-xl !font-mono !text-cyan-400">1.85</div>
            </div>
          </div>

          <div className="!space-y-3">
            <h4 className="!text-xs !font-bold !text-slate-400 uppercase !tracking-widest">Live Performance</h4>
            <div className="h-48 w-full bg-slate-950/30 rounded border border-slate-800 relative overflow-hidden">
              <div className="absolute inset-0 flex items-center justify-center !text-slate-600 !text-xs">
                [ Interactive Performance Chart Component ]
              </div>
              <svg className="absolute inset-0 w-full h-full opacity-30" preserveAspectRatio="none">
                <path d="M0,100 Q50,90 100,95 T200,80 T300,60 T400,70 T500,50 T600,40" fill="none" stroke={selectedStrategy.color} strokeWidth="2" />
              </svg>
            </div>
          </div>
        </Card>

        <Card title="Execution Logs" className="h-64" noPadding>
          <div className="flex-1 bg-slate-950/50 !p-4 !font-mono !text-xs overflow-y-auto h-full !text-slate-400">
            <div className="!mb-1"><span className="!text-slate-600">12:42:05</span> Strategy {selectedStrategy.name} active</div>
            <div className="!mb-1"><span className="!text-slate-600">12:42:06</span> Signal received: STRONG_BUY on BTCUSDT</div>
            <div className="!mb-1"><span className="!text-slate-600">12:42:07</span> Executing limit order @ 64,230.50...</div>
            <div className="!mb-1 !text-emerald-500"><span className="!text-slate-600">12:42:08</span> Order Filled (ID: 882934)</div>
            <div className="!mb-1"><span className="!text-slate-600">12:43:15</span> Monitoring position delta...</div>
          </div>
        </Card>
      </div>
    </div>
  );
};

const BacktestingView = ({ backtestStatus, handleRunBacktest }: any) => (
  <div className="grid grid-cols-1 lg:grid-cols-3 !gap-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
    <div className="!space-y-6">
      <Card title={<><Settings size={16} /> Simulation Config</>}>
        <div className="!space-y-3">
          <div className="!space-y-1">
            <label className="!text-xs !text-slate-500 !font-medium">Strategy</label>
            <div className="relative">
              <select className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 !text-sm !text-slate-300 focus:outline-none focus:border-cyan-500 appearance-none hover:border-slate-600 transition-colors">
                <option>Select a strategy</option>
                <option>HMM_Trend_v2</option>
                <option>MeanRev_Scalp</option>
              </select>
              <ChevronRight className="absolute right-3 top-2.5 !text-slate-500 rotate-90 pointer-events-none" size={14} />
            </div>
          </div>

          <div className="!space-y-1">
            <label className="!text-xs !text-slate-500 !font-medium">Symbols</label>
            <div className="flex items-center !gap-2 px-2.5 py-1.5 bg-slate-900 border border-slate-700 rounded-lg !text-sm !text-slate-300">
              <Filter size={14} className="!text-slate-500" />
              <span>All symbols</span>
            </div>
          </div>

          <div className="!space-y-1">
            <label className="!text-xs !text-slate-500 !font-medium">Date Range</label>
            <div className="flex items-center !gap-2 px-2.5 py-1.5 bg-slate-900 border border-slate-700 rounded-lg !text-sm !text-slate-300">
              <Clock size={14} className="!text-slate-500" />
              <span>11/3/2025 - 12/3/2025</span>
            </div>
          </div>

          <div className="grid grid-cols-2 !gap-4">
            <div className="!space-y-1">
              <label className="!text-xs !text-slate-500 !font-medium">Initial Capital</label>
              <input type="text" className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 !text-sm !text-slate-300 focus:outline-none focus:border-cyan-500" defaultValue="10000" />
            </div>
            <div className="!space-y-1">
              <label className="!text-xs !text-slate-500 !font-medium">Fee (bps)</label>
              <input type="text" className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 !text-sm !text-slate-300 focus:outline-none focus:border-cyan-500" defaultValue="5" />
            </div>
          </div>

          <div className="!space-y-1">
            <label className="!text-xs !text-slate-500 !font-medium">Slippage (bps)</label>
            <input type="text" className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 !text-sm !text-slate-300 focus:outline-none focus:border-cyan-500" defaultValue="2" />
          </div>

          <div className="!pt-4 flex !gap-2">
            <button
              onClick={handleRunBacktest}
              disabled={backtestStatus === 'running'}
              className={`
                flex-1 flex items-center justify-center !gap-2 !py-2 rounded-lg !text-sm !font-bold transition-all shadow-lg
                ${backtestStatus === 'running'
                  ? 'bg-slate-800 !text-slate-500 cursor-not-allowed border border-slate-700'
                  : 'bg-slate-100 !text-slate-900 hover:bg-white hover:shadow-cyan-500/20'}
              `}
            >
              {backtestStatus === 'running' ? (
                <><RefreshCw size={16} className="animate-spin" /> Running...</>
              ) : (
                <><Play size={16} className="fill-current" /> Run Backtest</>
              )}
            </button>
            <button className="!px-3 rounded-lg border border-slate-700 !text-slate-400 hover:!text-slate-200 hover:border-slate-500 transition-colors bg-slate-900 hover:bg-slate-800">
              <RotateCcw size={16} />
            </button>
          </div>
        </div>
      </Card>
    </div>

    <div className="lg:col-span-2">
      <Card title={<><Terminal size={16} /> Backtest Status</>} className="h-full min-h-[500px]" noPadding>
        <div className="flex-1 bg-slate-950/80 !p-4 !font-mono !text-xs flex flex-col">
          <div className="!text-slate-500 !mb-2 uppercase !tracking-wider !text-[10px]">Process Status</div>
          <div className="flex items-center !gap-3 !mb-6">
            <div className={`w-3 h-3 rounded-full ${backtestStatus === 'running' ? 'bg-amber-500 animate-pulse shadow-[0_0_8px_rgba(245,158,11,0.5)]' : 'bg-slate-700'}`}></div>
            <span className={`!text-sm !font-medium ${backtestStatus === 'running' ? '!text-amber-400' : '!text-slate-400'}`}>
              {backtestStatus === 'running' ? 'Running simulation environment...' : 'Environment Idle'}
            </span>
          </div>

          <div className="flex-1 border-t border-slate-800/50 !pt-4 !text-slate-400 space-y-1.5">
            {backtestStatus === 'running' ? (
              <div className="space-y-1.5 animate-in fade-in duration-300">
                <div className="!text-slate-500">[INFO] Initializing engine wrapper v2.4.0...</div>
                <div className="!text-slate-500">[INFO] Loading historical data for BTC-USDT (1h candles)...</div>
                <div className="!text-slate-300">[INFO] Replaying market stream from 11/03/2025...</div>
                <div className="!text-emerald-400 !font-bold">[EXEC] Order placed: BUY 0.5 BTC @ 42,100.00 (Strategy: HMM_Trend)</div>
                <div className="!text-slate-500">[INFO] Processing tick 4502/12000...</div>
              </div>
            ) : (
              <div className="opacity-30 italic flex items-center justify-center h-full !text-slate-600">
                Waiting for simulation command...
              </div>
            )}
          </div>

          {backtestStatus === 'running' && (
            <div className="!mt-6">
              <div className="flex justify-between !text-xs !mb-2 !font-mono">
                <span className="!text-slate-400">Progress</span>
                <span className="!text-cyan-400 !font-bold">45%</span>
              </div>
              <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                <div className="h-full bg-cyan-500 w-[45%] rounded-full animate-[pulse_1s_ease-in-out_infinite] shadow-[0_0_10px_currentColor]"></div>
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  </div>
);

const FundingView = ({ capitalAllocations, symbolExposure }: any) => (
  <div className="grid grid-cols-1 lg:grid-cols-3 !gap-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
    <div className="!space-y-6">
      <Card title={<><Battery size={16} /> Capital Buckets</>}
        action={
          <button className="!text-xs flex items-center !gap-1 !text-cyan-400 hover:!text-cyan-300 transition-colors">
            <Save size={12} /> Save
          </button>
        }
      >
        <div className="!space-y-3">
          <p className="!text-xs !text-slate-500 !mb-4">Update allocation weights used by the allocator. Values must sum to 1.0.</p>
          {capitalAllocations.map((item: any, idx: number) => (
            <ProgressBar key={idx} label={item.label} value={item.value} color={item.color} />
          ))}
        </div>
        <div className="!mt-6 !pt-4 border-t border-slate-800 flex justify-between items-center">
          <span className="!text-sm !text-slate-400">Total Allocated</span>
          <span className="!text-sm !font-mono !text-emerald-400 !font-bold">100.0%</span>
        </div>
      </Card>

      <Card title={<><Wallet size={16} /> Cash on Hand</>} className="!text-center items-center">
        <div className="flex flex-col items-center justify-center !mb-2">
          <span className="!text-3xl !font-mono !text-white !font-bold !tracking-tight">$45,230.50</span>
          <div className="!px-2 !py-1 !mt-2 rounded bg-emerald-500/10 border border-emerald-500/20 !text-emerald-400 !text-[10px] !font-bold uppercase !tracking-wider">Available</div>
        </div>
        <p className="!text-xs !text-slate-500 !text-center">Liquid capital available for immediate deployment across all connected venues.</p>
      </Card>
    </div>

    <div className="lg:col-span-2 grid grid-cols-1 !gap-6">
      <Card title={<><BarChart2 size={16} /> Total Equity</>}>
        <div className="h-48 w-full relative group cursor-crosshair">
          <div className="absolute inset-0 grid grid-cols-6 grid-rows-4 !gap-4 pointer-events-none">
            {[...Array(24)].map((_, i) => <div key={i} className="border-r border-t border-slate-800/30 first:border-l last:border-b-0"></div>)}
          </div>
          <svg className="w-full h-full overflow-visible" preserveAspectRatio="none">
            <path d="M0,150 C50,140 100,160 150,120 C200,80 250,100 300,90 C350,80 400,60 450,50 C500,40 550,55 600,30 L600,200 L0,200 Z" fill="url(#gradient)" opacity="0.2" />
            <path d="M0,150 C50,140 100,160 150,120 C200,80 250,100 300,90 C350,80 400,60 450,50 C500,40 550,55 600,30" fill="none" stroke="#22d3ee" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            <defs>
              <linearGradient id="gradient" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.5" />
                <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
              </linearGradient>
            </defs>
          </svg>
          <div className="absolute top-8 right-12 bg-slate-900/90 backdrop-blur border border-slate-700 !p-3 rounded !text-xs opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none shadow-xl">
            <div className="!text-slate-400 !mb-1">Current Equity</div>
            <div className="!text-white !font-mono !font-bold !text-lg">$125,430.00</div>
          </div>
        </div>
        <div className="flex justify-between !mt-2 !text-xs !text-slate-500 !font-mono">
          <span>09:00</span><span>10:00</span><span>11:00</span><span>12:00</span><span>13:00</span><span>14:00</span>
        </div>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 !gap-6">
        <Card title={<><ShieldAlert size={16} /> Symbol Exposure</>}>
          <div className="!space-y-3">
            {symbolExposure.map((sym: any, i: number) => (
              <div key={i} className="relative">
                <div className="flex justify-between items-center !text-sm z-10 relative !mb-1">
                  <span className="!font-mono !font-bold !text-slate-200">{sym.symbol}</span>
                  <span className={`!font-mono ${sym.side === 'long' ? '!text-emerald-400' : '!text-rose-400'}`}>{sym.amount}</span>
                </div>
                <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                  <div className={`h-full rounded-full ${sym.side === 'long' ? 'bg-emerald-500' : 'bg-rose-500'}`} style={{ width: `${sym.percent}%` }} />
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title={<><Activity size={16} /> Venue PnL Snapshot</>}>
          <div className="!space-y-3">
            <div className="flex items-center justify-between !p-2 rounded bg-slate-900/40 border border-slate-800/50">
              <div className="flex items-center !gap-3">
                <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                <span className="!text-sm !font-medium !text-slate-300">Binance</span>
              </div>
              <span className="!font-mono !text-emerald-400 !text-sm !font-bold">+$1,240.50</span>
            </div>
            <div className="flex items-center justify-between !p-2 rounded bg-slate-900/40 border border-slate-800/50">
              <div className="flex items-center !gap-3">
                <div className="w-2 h-2 rounded-full bg-slate-600"></div>
                <span className="!text-sm !font-medium !text-slate-300">Bybit</span>
              </div>
              <span className="!font-mono !text-slate-500 !text-sm !font-bold">$0.00</span>
            </div>
            <div className="flex items-center justify-between !p-2 rounded bg-slate-900/40 border border-slate-800/50">
              <div className="flex items-center !gap-3">
                <div className="w-2 h-2 rounded-full bg-rose-500"></div>
                <span className="!text-sm !font-medium !text-slate-300">Kraken</span>
              </div>
              <span className="!font-mono !text-rose-400 !text-sm !font-bold">-$45.20</span>
            </div>
          </div>
        </Card>
      </div>
    </div>
  </div>
);

const SettingsView = () => (
  <div className="max-w-4xl !mx-auto !space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
    <Card title="OPS API Token" action={
      <button className="flex items-center gap-1.5 !px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 !text-xs !font-medium !text-slate-300 transition-colors">
        <RefreshCw size={12} /> Refresh config
      </button>
    }>
      <div className="space-y-1.5">
        <p className="!text-xs !text-slate-500">Provide the bearer token required by the Ops API. The value stays in memory only.</p>
        <input type="password" className="w-full bg-slate-950/50 border border-slate-800 rounded-lg px-2.5 py-1.5 !text-sm !font-mono !text-slate-300 placeholder:!text-slate-700 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/50 transition-all" placeholder="Paste bearer token here..." />
      </div>
    </Card>

    <Card title="X-Ops-Token header">
      <div className="space-y-1.5">
        <p className="!text-xs !text-slate-500">Paste OPS_API_TOKEN value</p>
        <input type="password" className="w-full bg-slate-950/50 border border-slate-800 rounded-lg px-2.5 py-1.5 !text-sm !font-mono !text-slate-300 placeholder:!text-slate-700 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/50 transition-all" placeholder="Paste token header value..." />
        <p className="!text-[10px] !text-slate-600 !font-mono !pt-1">When running locally, export OPS_API_TOKEN or OPS_API_TOKEN_FILE and reuse that value here for authenticated updates.</p>
      </div>
    </Card>

    <Card title="Operator (audit log, required)">
      <div className="space-y-1.5">
        <p className="!text-xs !text-slate-500">Enter your call-sign or initials</p>
        <input type="text" className="w-full bg-slate-950/50 border border-slate-800 rounded-lg px-2.5 py-1.5 !text-sm !font-mono !text-slate-300 placeholder:!text-slate-700 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/50 transition-all" placeholder="e.g. VISOR_1" />
      </div>
    </Card>

    <Card title="Protection & Automation Flags" action={
      <div className="flex items-center !gap-2">
        <button className="flex items-center gap-1.5 !px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 !text-xs !font-medium !text-slate-300 transition-colors"><Copy size={12} /> Copy overrides</button>
        <button className="flex items-center gap-1.5 !px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 !text-xs !font-medium !text-slate-300 transition-colors"><Download size={12} /> Download config</button>
      </div>
    }>
      <div className="!space-y-3">
        <p className="!text-xs !text-slate-500 !mb-2">Values reflect config/runtime.yaml merged with overrides.</p>
        <div className="grid grid-cols-1 md:grid-cols-2 !gap-4">
          <FlagItem title="Dry Run" description="Route execution in simulation mode without placing real orders." status="ENABLED" />
          <FlagItem title="Symbol Scanner" description="Continuously refresh the universe scanner feed." status="DISABLED" />
          <FlagItem title="Breakeven Allowed" description="Permit breakeven exits when a soft breach fires." status="DISABLED" />
          <FlagItem title="Cancel Entries" description="Cancel outstanding entry orders when a soft breach triggers." status="DISABLED" />
          <FlagItem title="Soft Breach Guard" description="Alerts and guard-rail for risk rails before hard stops trigger." status="DISABLED" />
          <FlagItem title="Soft Breach tighten stop-loss" description="Percentage applied to tighten the stop-loss when a soft breach occurs." value="--" />
        </div>
      </div>
    </Card>

    <Card title="Runtime Overrides" action={<button className="!text-xs !font-bold !text-slate-400 hover:!text-white transition-colors">Save overrides</button>}>
      <div className="space-y-1.5">
        <p className="!text-xs !text-slate-500">Edit the JSON payload sent to PUT /api/config.</p>
        <div className="relative !font-mono !text-xs">
          <textarea className="w-full h-24 bg-slate-950 border border-slate-800 rounded-lg !p-3 !text-slate-300 focus:outline-none focus:border-cyan-500/50 resize-none" defaultValue="{}" />
        </div>
        <p className="!text-[10px] !text-slate-600 !font-mono">Example: &#123;"DRY_RUN": false, "SOFT_BREACH_ENABLED": true&#125;</p>
      </div>
    </Card>

    <Card title="Effective Configuration">
      <div className="space-y-1.5">
        <p className="!text-xs !text-slate-500">Resulting payload served to clients (config/runtime.yaml merged with overrides).</p>
        <div className="w-full h-36 bg-slate-950 border border-slate-800 rounded-lg !p-3 !text-xs !font-mono text-emerald-500/80 overflow-y-auto whitespace-pre">
          {`{
  "global": {
    "trading_enabled": false
  },
  "strategies": {},
  "risk": {},
  "DRY_RUN": true
}`}
        </div>
        <p className="!text-[10px] !text-slate-600 !font-mono !pt-1">Updates apply immediately and are persisted by the Ops service. Keep your token secure; the Command Center never stores it beyond this session.</p>
      </div>
    </Card>
  </div>
);

// --- Main Application ---

export default function NautilusTerminal() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [tradingMode, setTradingMode] = useState('paper');
  const [isPaused, setIsPaused] = useState(false);
  const [backtestStatus, setBacktestStatus] = useState('idle');
  const [showToast, setShowToast] = useState(false);

  // --- Mock Data ---

  const capitalAllocations = [
    { label: "Crypto Majors", value: 45, amount: "45%", color: "bg-indigo-500" },
    { label: "Forex Scalp", value: 30, amount: "30%", color: "bg-cyan-500" },
    { label: "DeFi Yield", value: 15, amount: "15%", color: "bg-emerald-500" },
    { label: "Cash Reserves", value: 10, amount: "10%", color: "bg-slate-600" },
  ];

  const symbolExposure = [
    { symbol: "BTC-USDT", amount: "$42,500", percent: 75, side: "long" },
    { symbol: "ETH-PERP", amount: "$12,200", percent: 40, side: "long" },
    { symbol: "SOL-USDT", amount: "-$5,400", percent: 15, side: "short" },
  ];

  const strategies: Strategy[] = [
    { name: "HMM_Trend_v2", status: "active", pnl: "+12.4%", chartData: [5, 10, 8, 15, 20, 25], color: "#34d399" },
    { name: "MeanRev_Scalp", status: "active", pnl: "+3.2%", chartData: [10, 8, 12, 10, 15, 12], color: "#60a5fa" },
    { name: "Meme_Sniper", status: "paused", pnl: "-0.5%", chartData: [5, 4, 3, 4, 3, 2], color: "#94a3b8" },
  ];

  const orderLog: Order[] = [
    { time: "12:42:05", symbol: "BTCUSDT", type: "BUY", price: "64,230.50", size: "0.05", status: "FILLED" },
    { time: "12:41:58", symbol: "ETHUSDT", type: "SELL", price: "3,450.20", size: "1.20", status: "FILLED" },
    { time: "12:41:20", symbol: "SOLUSDT", type: "BUY", price: "145.60", size: "15.0", status: "PARTIAL" },
    { time: "12:40:45", symbol: "BTCUSDT", type: "BUY", price: "64,210.00", size: "0.10", status: "FILLED" },
    { time: "12:39:12", symbol: "AVAXUSDT", type: "SELL", price: "38.45", size: "50.0", status: "FILLED" },
    { time: "12:38:05", symbol: "BTCUSDT", type: "BUY", price: "64,180.00", size: "0.02", status: "FILLED" },
    { time: "12:37:22", symbol: "ETHUSDT", type: "BUY", price: "3,440.00", size: "0.50", status: "FILLED" },
  ];

  const featureImportance: Feature[] = [
    { label: "Order Book Imbalance (5m)", value: 85, amount: "0.85", color: "bg-purple-500" },
    { label: "Volatility Delta (1h)", value: 65, amount: "0.65", color: "bg-purple-500" },
    { label: "funding_rate_predicted", value: 45, amount: "0.45", color: "bg-slate-600" },
    { label: "whale_wallet_flow", value: 30, amount: "0.30", color: "bg-slate-600" },
    { label: "sentiment_score_x", value: 15, amount: "0.15", color: "bg-slate-600" },
  ];

  const systemStatus: SystemStatus[] = [
    { label: "ENGINE", status: "OK", color: "!text-emerald-400" },
    { label: "DATA FEED", status: "OK", color: "!text-emerald-400" },
    { label: "EXECUTION", status: "OK", color: "!text-emerald-400" },
    { label: "ML TRAINING", status: "TRAINING", color: "!text-amber-400 animate-pulse" },
  ];

  const systemLogs = [
    "11:53:11 PM [INFO] Order filled: BUY ETHUSDT @ 3420.50",
    "11:53:11 PM [INFO] Engine initialized successfully",
    "11:53:11 PM [INFO] Connected to Binance Futures API (v2)",
    "11:53:11 PM [INFO] ML Model loaded: v2.1.0-RC3",
    "11:53:11 PM [INFO] Websocket stream active",
    "11:53:10 PM [WARN] Latency spike detected on eu-central-1 (82ms)",
    "11:53:09 PM [INFO] Strategy HMM_Trend_v2 rebalancing...",
    "11:53:05 PM [INFO] Database snapshot saved (size: 45MB)",
  ];

  const handleRunBacktest = () => {
    setBacktestStatus('running');
    setTimeout(() => {
      setBacktestStatus('idle');
      setShowToast(true);
    }, 3000);
  }

  useEffect(() => {
    if (showToast) {
      const timer = setTimeout(() => setShowToast(false), 5000);
      return () => clearTimeout(timer);
    }
  }, [showToast]);

  return (
    <div className="min-h-screen bg-slate-950 !text-slate-200 !font-sans selection:bg-cyan-500/30 overflow-x-hidden relative">

      <ScanlineOverlay />
      <AIAssistant />

      {showToast && (
        <Toast message="Unable to load strategies" detail={`{"detail": "Not Found"}`} />
      )}

      <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur-md sticky top-0 z-50 shadow-lg shadow-cyan-500/5 h-14">
        <div className="max-w-7xl !mx-auto !px-4 lg:!px-6 h-full flex items-center justify-between">
          <div className="flex items-center !gap-6">
            <div className="flex items-center !gap-3 group cursor-pointer" onClick={() => setActiveTab('dashboard')}>
              <div className="w-8 h-8 rounded bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center shadow-[0_0_15px_rgba(6,182,212,0.5)] group-hover:shadow-[0_0_20px_rgba(6,182,212,0.8)] transition-shadow">
                <Anchor className="!text-white" size={18} />
              </div>
              <div className="flex flex-col !leading-none">
                <span className="!font-bold !tracking-wide !text-slate-100 group-hover:!text-cyan-400 transition-colors !text-lg">NAUTILUS</span>
                <span className="!text-[10px] !text-slate-500 !font-mono !tracking-widest uppercase">Terminal v2.4</span>
              </div>
            </div>

            <div className="h-6 w-px bg-slate-800 !mx-2 hidden sm:block"></div>

            <div className="flex bg-slate-900 border border-slate-800 rounded-lg !p-1">
              <button onClick={() => setTradingMode('paper')} className={`!px-3 !py-1 !text-xs !font-bold rounded transition-colors ${tradingMode === 'paper' ? 'bg-amber-500/10 !text-amber-500 shadow-[0_0_10px_rgba(245,158,11,0.2)]' : '!text-slate-500 hover:!text-slate-300'}`}>PAPER</button>
              <button onClick={() => setTradingMode('live')} className={`!px-3 !py-1 !text-xs !font-bold rounded transition-colors ${tradingMode === 'live' ? 'bg-rose-500/10 !text-rose-500 shadow-[0_0_10px_rgba(244,63,94,0.2)]' : '!text-slate-500 hover:!text-slate-300'}`}>LIVE</button>
            </div>
          </div>

          <div className="flex items-center !gap-3">
            <div className="hidden md:flex items-center !gap-2 !mr-4 bg-slate-900 border border-slate-800 rounded-lg !px-3 py-1.5">
              <div className="flex items-center !gap-2 !pr-3 border-r border-slate-800">
                <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
                <span className="!text-xs !font-mono !text-slate-400">Binance: <span className="!text-emerald-400 !font-bold">50ms</span></span>
              </div>
              <div className="!pl-1">
                <span className="!text-xs !font-mono !text-slate-400">Q0: <span className="!text-slate-200">Idle</span></span>
              </div>
            </div>

            <button onClick={() => setIsPaused(!isPaused)} className={`!p-2 rounded-lg border transition-all ${isPaused ? 'bg-amber-500/10 border-amber-500/50 !text-amber-500 shadow-[0_0_10px_rgba(245,158,11,0.2)]' : 'bg-slate-800 border-slate-700 hover:bg-slate-700 !text-slate-300'}`} title={isPaused ? "Resume Trading" : "Pause Trading"}>
              {isPaused ? <PlayCircle size={18} /> : <PauseCircle size={18} />}
            </button>

            <button className="!p-2 rounded-lg bg-slate-800 border border-slate-700 hover:bg-slate-700 !text-slate-300 transition-colors" title="Flatten All Positions">
              <RefreshCw size={18} />
            </button>

            <button className="flex items-center !gap-2 !px-3 !py-2 rounded-lg bg-rose-500/10 border border-rose-500/50 !text-rose-500 hover:bg-rose-500 hover:!text-white transition-all duration-300 shadow-[0_0_15px_rgba(244,63,94,0.1)] group">
              <Power size={16} />
              <span className="!text-xs !font-bold !tracking-wider">KILL</span>
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-[1600px] !mx-auto !px-8 lg:!px-12 !pt-8 !pb-8 relative z-10">

        <div className="grid grid-cols-2 md:grid-cols-4 !gap-x-8 !gap-y-6 !mb-12">
          <Card className="flex-col items-center justify-center !text-center !py-6 border-emerald-500/20 bg-emerald-500/5">
            <div className="!p-2 !mb-2 rounded-lg bg-emerald-500/20 !text-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.3)]"><DollarSign size={20} /></div>
            <StatValue label="Total PnL" value="+$12,450.00" subValue="+2.4%" type="positive" />
          </Card>
          <Card className="flex-col items-center justify-center !text-center !py-6 border-indigo-500/20 bg-indigo-500/5">
            <div className="!p-2 !mb-2 rounded-lg bg-indigo-500/20 !text-indigo-400 shadow-[0_0_10px_rgba(99,102,241,0.3)]"><Activity size={20} /></div>
            <StatValue label="Sharpe Ratio" value="1.50" subValue="Risk-adj" type="brand" />
          </Card>
          <Card className="flex-col items-center justify-center !text-center !py-6 border-amber-500/20 bg-amber-500/5">
            <div className="!p-2 !mb-2 rounded-lg bg-amber-500/20 !text-amber-400 shadow-[0_0_10px_rgba(245,158,11,0.3)]"><AlertTriangle size={20} /></div>
            <StatValue label="Max Drawdown" value="10.00%" subValue="Peak-Trough" type="warning" />
          </Card>
          <Card className="flex-col items-center justify-center !text-center !py-6 border-slate-700/50 bg-slate-800/30">
            <div className="!p-2 !mb-2 rounded-lg bg-slate-700/30 !text-slate-300"><Box size={20} /></div>
            <StatValue label="Open Positions" value="3" subValue="Active" />
          </Card>
        </div>

        <div className="flex overflow-x-auto !py-5 !gap-3 border-b border-slate-800 !mb-10 scrollbar-hide">
          <TabButton active={activeTab === 'dashboard'} onClick={() => setActiveTab('dashboard')} icon={LayoutDashboard} label="Dashboard" />
          <TabButton active={activeTab === 'neural'} onClick={() => setActiveTab('neural')} icon={Cpu} label="Neural Link" />
          <TabButton active={activeTab === 'system'} onClick={() => setActiveTab('system')} icon={Activity} label="System Internals" />
          <TabButton active={activeTab === 'strategy'} onClick={() => setActiveTab('strategy')} icon={Zap} label="Strategy" />
          <TabButton active={activeTab === 'backtesting'} onClick={() => setActiveTab('backtesting')} icon={Terminal} label="Backtesting" />
          <TabButton active={activeTab === 'funding'} onClick={() => setActiveTab('funding')} icon={Wallet} label="Funding" />
          <TabButton active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} icon={Settings} label="Settings" />
        </div>

        {activeTab === 'dashboard' && <DashboardView strategies={strategies} orderLog={orderLog} />}
        {activeTab === 'neural' && <NeuralView featureImportance={featureImportance} />}
        {activeTab === 'system' && <SystemView systemStatus={systemStatus} systemLogs={systemLogs} />}
        {activeTab === 'strategy' && <StrategyView strategies={strategies} />}
        {activeTab === 'backtesting' && <BacktestingView backtestStatus={backtestStatus} handleRunBacktest={handleRunBacktest} />}
        {activeTab === 'funding' && <FundingView capitalAllocations={capitalAllocations} symbolExposure={symbolExposure} />}
        {activeTab === 'settings' && <SettingsView />}

      </main>
    </div>
  );
}


