import { useMemo } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

function buildHistogram(values: number[], bins = 30) {
  if (!values.length) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const step = (max - min) / (bins || 1) || 1;
  const buckets = Array.from({ length: Math.max(1, bins) }, (_, index) => ({
    x0: min + index * step,
    x1: min + (index + 1) * step,
    count: 0,
  }));

  for (const value of values) {
    const bucketIndex = Math.min(buckets.length - 1, Math.floor((value - min) / step));
    buckets[bucketIndex].count += 1;
  }

  return buckets.map((bucket) => ({
    bin: `${bucket.x0.toFixed(3)}–${bucket.x1.toFixed(3)}`,
    count: bucket.count,
  }));
}

type ReturnsHistogramProps = {
  returns: number[];
  bins?: number;
};

export function ReturnsHistogram({ returns, bins = 30 }: ReturnsHistogramProps) {
  const data = useMemo(() => buildHistogram(returns, bins), [returns, bins]);

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ left: 8, right: 8, top: 8, bottom: 24 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis
          dataKey="bin"
          interval={Math.ceil((bins || 30) / 10)}
          angle={-30}
          textAnchor="end"
          height={50}
        />
        <YAxis />
        <Tooltip />
        <Bar dataKey="count" />
      </BarChart>
    </ResponsiveContainer>
  );
}
