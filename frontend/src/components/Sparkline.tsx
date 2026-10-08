import type { TrendPoint } from "../api";

export default function Sparkline({ points, label }: { points: TrendPoint[]; label: string }) {
  const w = 240, h = 64, pad = 8;
  if (points.length === 0) return null;
  const values = points.map((p) => p.value);
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const x = (i: number) => (points.length === 1 ? w / 2 : pad + (i * (w - 2 * pad)) / (points.length - 1));
  const y = (v: number) => h - pad - ((v - min) / span) * (h - 2 * pad);
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`).join(" ");
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${label}: ${points.map((p) => `${p.display_value} on ${p.date}`).join(", ")}`}>
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" />
      {points.map((p, i) => (
        <circle key={p.item_id} cx={x(i)} cy={y(p.value)} r="3" fill="currentColor" />
      ))}
    </svg>
  );
}
