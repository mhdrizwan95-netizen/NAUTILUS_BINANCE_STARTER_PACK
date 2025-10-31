import {
  Brush,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

type EquityCurvesProps = {
  data: Array<{ t: string; [strategyId: string]: number }>;
  series: Array<{ key: string; label: string }>;
};

export function EquityCurves({ data, series }: EquityCurvesProps) {
  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={data} margin={{ left: 8, right: 8, top: 8, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="t" />
        <YAxis />
        <Tooltip />
        <Legend />
        {series.map((definition) => (
          <Line
            key={definition.key}
            type="monotone"
            dataKey={definition.key}
            name={definition.label}
            dot={false}
            strokeWidth={1.7}
          />
        ))}
        <Brush dataKey="t" height={24} />
      </LineChart>
    </ResponsiveContainer>
  );
}
