import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type PnlBySymbolProps = {
  data: Array<{ symbol: string; pnl: number }>;
};

export function PnlBySymbol({ data }: PnlBySymbolProps) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ left: 8, right: 8, top: 8, bottom: 24 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="symbol" angle={-30} textAnchor="end" height={48} />
        <YAxis />
        <Tooltip />
        <ReferenceLine y={0} />
        <Bar dataKey="pnl" />
      </BarChart>
    </ResponsiveContainer>
  );
}
