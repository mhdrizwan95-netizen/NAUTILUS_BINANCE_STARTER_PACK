import { Wallet, TrendingUp, ArrowUpDown, PieChart } from 'lucide-react';
import { PieChart as RechartsPie, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts';
export function FundingTab() {
  // Mock funding data
  const venueFunds = [
    { venue: 'Binance', available: 125000, allocated: 85000, reserved: 15000, type: 'crypto' as const },
    { venue: 'Bybit', available: 80000, allocated: 55000, reserved: 10000, type: 'crypto' as const },
    { venue: 'IBKR', available: 200000, allocated: 145000, reserved: 25000, type: 'equities' as const },
    { venue: 'OANDA', available: 75000, allocated: 50000, reserved: 5000, type: 'fx' as const },
  ];

  const totalAvailable = venueFunds.reduce((sum, v) => sum + v.available, 0);
  const totalAllocated = venueFunds.reduce((sum, v) => sum + v.allocated, 0);
  const totalReserved = venueFunds.reduce((sum, v) => sum + v.reserved, 0);
  const totalFunds = totalAvailable + totalAllocated + totalReserved;

  // Allocation pie chart data
  const allocationData = venueFunds.map(v => ({
    name: v.venue,
    value: v.allocated,
    type: v.type,
  }));

  const COLORS = {
    crypto: '#06b6d4',
    equities: '#fbbf24',
    fx: '#a78bfa',
  };

  // Fund flow history (mock)
  const fundFlowData = [
    { date: 'Oct 23', deposits: 50000, withdrawals: 20000 },
    { date: 'Oct 24', deposits: 30000, withdrawals: 15000 },
    { date: 'Oct 25', deposits: 75000, withdrawals: 10000 },
    { date: 'Oct 26', deposits: 40000, withdrawals: 25000 },
    { date: 'Oct 27', deposits: 60000, withdrawals: 30000 },
    { date: 'Oct 28', deposits: 45000, withdrawals: 20000 },
    { date: 'Oct 29', deposits: 55000, withdrawals: 15000 },
  ];

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  };

  return (
    <div className="p-6 space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-4">
        <FundCard
          label="Total Capital"
          value={formatCurrency(totalFunds)}
          icon={<Wallet className="w-5 h-5" />}
          color="cyan"
        />
        <FundCard
          label="Available"
          value={formatCurrency(totalAvailable)}
          subtitle={`${((totalAvailable / totalFunds) * 100).toFixed(1)}%`}
          icon={<TrendingUp className="w-5 h-5" />}
          color="emerald"
        />
        <FundCard
          label="Allocated"
          value={formatCurrency(totalAllocated)}
          subtitle={`${((totalAllocated / totalFunds) * 100).toFixed(1)}%`}
          icon={<ArrowUpDown className="w-5 h-5" />}
          color="amber"
        />
        <FundCard
          label="Reserved"
          value={formatCurrency(totalReserved)}
          subtitle={`${((totalReserved / totalFunds) * 100).toFixed(1)}%`}
          icon={<PieChart className="w-5 h-5" />}
          color="violet"
        />
      </div>

      <div className="grid grid-cols-12 gap-4">
        {/* Venue Breakdown */}
        <div className="col-span-7 bg-zinc-900/50 backdrop-blur-sm border border-zinc-800/50 rounded-xl p-4">
          <h3 className="text-zinc-400 mb-4">Venue Breakdown</h3>
          <div className="space-y-3">
            {venueFunds.map((fund) => {
              const total = fund.available + fund.allocated + fund.reserved;
              const venueColor = COLORS[fund.type];
              
              return (
                <div
                  key={fund.venue}
                  className="p-4 rounded-lg bg-zinc-800/30 hover:bg-zinc-800/50 transition-colors"
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: venueColor }}
                      />
                      <span className="text-zinc-100">{fund.venue}</span>
                      <span className="text-xs text-zinc-500 px-2 py-1 rounded-md bg-zinc-800/50">
                        {fund.type}
                      </span>
                    </div>
                    <span className="font-mono text-zinc-300">
                      {formatCurrency(total)}
                    </span>
                  </div>

                  {/* Progress bars */}
                  <div className="space-y-2">
                    <FundBar
                      label="Available"
                      value={fund.available}
                      total={total}
                      color="emerald"
                    />
                    <FundBar
                      label="Allocated"
                      value={fund.allocated}
                      total={total}
                      color="cyan"
                    />
                    <FundBar
                      label="Reserved"
                      value={fund.reserved}
                      total={total}
                      color="zinc"
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Allocation Pie Chart */}
        <div className="col-span-5 bg-zinc-900/50 backdrop-blur-sm border border-zinc-800/50 rounded-xl p-4">
          <h3 className="text-zinc-400 mb-4">Capital Allocation</h3>
          <ResponsiveContainer width="100%" height={250}>
            <RechartsPie>
              <Pie
                data={allocationData}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={90}
                paddingAngle={2}
                dataKey="value"
              >
                {allocationData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[entry.type]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  backgroundColor: '#18181b',
                  border: '1px solid #3f3f46',
                  borderRadius: '8px',
                }}
                formatter={(value: number) => formatCurrency(value)}
              />
            </RechartsPie>
          </ResponsiveContainer>

          {/* Legend */}
          <div className="mt-4 space-y-2">
            {allocationData.map((item) => (
              <div key={item.name} className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <div
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: COLORS[item.type] }}
                  />
                  <span className="text-zinc-400">{item.name}</span>
                </div>
                <span className="font-mono text-zinc-300">
                  {formatCurrency(item.value)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Fund Flow History */}
        <div className="col-span-12 bg-zinc-900/50 backdrop-blur-sm border border-zinc-800/50 rounded-xl p-4">
          <h3 className="text-zinc-400 mb-4">Fund Flow History (7 Days)</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={fundFlowData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
              <XAxis dataKey="date" stroke="#71717a" className="text-xs" />
              <YAxis stroke="#71717a" className="text-xs" />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#18181b',
                  border: '1px solid #3f3f46',
                  borderRadius: '8px',
                }}
                formatter={(value: number) => formatCurrency(value)}
              />
              <Bar dataKey="deposits" fill="#10b981" radius={[4, 4, 0, 0]} />
              <Bar dataKey="withdrawals" fill="#ef4444" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

interface FundCardProps {
  label: string;
  value: string;
  subtitle?: string;
  icon: React.ReactNode;
  color: 'cyan' | 'emerald' | 'amber' | 'violet';
}

function FundCard({ label, value, subtitle, icon, color }: FundCardProps) {
  const colorClasses = {
    cyan: 'text-cyan-400 border-cyan-400/30',
    emerald: 'text-emerald-400 border-emerald-400/30',
    amber: 'text-amber-400 border-amber-400/30',
    violet: 'text-violet-400 border-violet-400/30',
  };

  return (
    <div className={`bg-zinc-900/50 backdrop-blur-sm border ${colorClasses[color]} rounded-xl p-4`}>
      <div className="flex items-center gap-2 mb-2">
        <div className={colorClasses[color].split(' ')[0]}>{icon}</div>
        <span className="text-xs text-zinc-500">{label}</span>
      </div>
      <div className={`font-mono ${colorClasses[color].split(' ')[0]}`}>
        {value}
      </div>
      {subtitle && (
        <div className="text-xs text-zinc-600 mt-1">{subtitle}</div>
      )}
    </div>
  );
}

interface FundBarProps {
  label: string;
  value: number;
  total: number;
  color: 'emerald' | 'cyan' | 'zinc';
}

function FundBar({ label, value, total, color }: FundBarProps) {
  const percentage = (value / total) * 100;
  const colorClasses = {
    emerald: 'bg-emerald-400',
    cyan: 'bg-cyan-400',
    zinc: 'bg-zinc-600',
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-zinc-500 w-20">{label}</span>
      <div className="flex-1 h-2 bg-zinc-800 rounded-full overflow-hidden">
        <div
          className={`h-full ${colorClasses[color]} transition-all duration-500`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <span className="text-xs text-zinc-400 font-mono w-16 text-right">
        {percentage.toFixed(1)}%
      </span>
    </div>
  );
}
