"use client";

import { useId, useState } from "react";

/* ------------------------------------------------------------------ */
/* AreaChart — smooth, dependency-free SVG area/line chart with a      */
/* hover crosshair and tooltip. Axis labels are HTML overlays so they  */
/* never distort when the chart is scaled to the container width.      */
/* ------------------------------------------------------------------ */

interface ChartPoint {
  label: string;
  value: number;
}

export function AreaChart({
  data,
  height = 240,
  valueFormatter = (v: number) => String(v),
  labelFormatter,
}: {
  data: ChartPoint[];
  height?: number;
  valueFormatter?: (v: number) => string;
  labelFormatter?: (label: string) => string;
}) {
  const gradId = useId().replace(/:/g, "");
  const [hover, setHover] = useState<number | null>(null);

  if (data.length === 0) return null;

  const w = 760;
  const h = height;
  const pad = { top: 14, right: 16, bottom: 26, left: 36 };
  const innerW = w - pad.left - pad.right;
  const innerH = h - pad.top - pad.bottom;

  const max = Math.max(1, ...data.map((d) => d.value));
  const step = Math.pow(10, String(Math.round(max)).length - 1);
  const yMax = Math.max(step, Math.ceil(max / step) * step);

  const x = (i: number) =>
    pad.left + (data.length <= 1 ? innerW / 2 : (i / (data.length - 1)) * innerW);
  const y = (v: number) => pad.top + innerH - (v / yMax) * innerH;

  const linePath = data
    .map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(d.value).toFixed(1)}`)
    .join(" ");

  // Catmull-Rom -> cubic Bézier smoothing for a premium line feel.
  const smoothPath = (() => {
    if (data.length < 3) return linePath;
    let d = `M${x(0)},${y(data[0].value)}`;
    for (let i = 0; i < data.length - 1; i++) {
      const p0 = data[Math.max(0, i - 1)];
      const p1 = data[i];
      const p2 = data[i + 1];
      const p3 = data[Math.min(data.length - 1, i + 2)];
      const c1x = x(i) + (x(i + 1) - x(Math.max(0, i - 1))) / 6;
      const c1y = y(p1.value) + (y(p2.value) - y(p0.value)) / 6;
      const c2x = x(i + 1) - (x(Math.min(data.length - 1, i + 2)) - x(i)) / 6;
      const c2y = y(p2.value) - (y(p3.value) - y(p1.value)) / 6;
      d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${x(i + 1).toFixed(1)},${y(p2.value).toFixed(1)}`;
    }
    return d;
  })();

  const areaPath = `${smoothPath} L${x(data.length - 1).toFixed(1)},${pad.top + innerH} L${x(0).toFixed(1)},${pad.top + innerH} Z`;

  const yTicks = [0, yMax / 2, yMax];
  const xTickIndexes = [0, Math.floor((data.length - 1) / 2), data.length - 1];

  function handlePointer(e: React.PointerEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    setHover(Math.round(pct * (data.length - 1)));
  }

  const hovered = hover !== null ? data[hover] : null;

  return (
    <div>
      <div
        className="relative w-full select-none"
        style={{ height }}
        onPointerMove={handlePointer}
        onPointerLeave={() => setHover(null)}
      >
        {/* y-axis labels (HTML overlay, never distorted) */}
        {yTicks.map((t) => (
          <span
            key={t}
            className="pointer-events-none absolute left-0 -translate-y-1/2 text-[10px] tabular-nums text-zinc-400"
            style={{ top: `${(y(t) / h) * 100}%` }}
          >
            {valueFormatter(t)}
          </span>
        ))}
        {/* x-axis labels */}
        {xTickIndexes.map((i) => (
          <span
            key={i}
            className="pointer-events-none absolute bottom-0 text-[10px] text-zinc-400"
            style={{
              left: `${(x(i) / w) * 100}%`,
              transform: i === 0 ? "none" : i === data.length - 1 ? "translateX(-100%)" : "translateX(-50%)",
            }}
          >
            {labelFormatter ? labelFormatter(data[i].label) : data[i].label}
          </span>
        ))}

        <svg
          className="absolute inset-0 h-full w-full overflow-visible"
          viewBox={`0 0 ${w} ${h}`}
          preserveAspectRatio="none"
          role="img"
          aria-label="Area chart"
        >
          <defs>
            <linearGradient id={`${gradId}-fill`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2563eb" stopOpacity={0.14} />
              <stop offset="100%" stopColor="#2563eb" stopOpacity={0} />
            </linearGradient>
          </defs>

          {yTicks.map((t) => (
            <line
              key={t}
              x1={pad.left}
              x2={w - pad.right}
              y1={y(t)}
              y2={y(t)}
              stroke="#e4e4e7"
              strokeWidth={1}
              strokeDasharray={t === 0 ? undefined : "3 4"}
              vectorEffect="non-scaling-stroke"
            />
          ))}

          {hover !== null && (
            <g>
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1={pad.top}
                y2={pad.top + innerH}
                stroke="#c7c7d1"
                strokeWidth={1}
                strokeDasharray="3 3"
                vectorEffect="non-scaling-stroke"
              />
              <circle cx={x(hover)} cy={y(data[hover].value)} r={4} fill="#2563eb" stroke="#fff" strokeWidth={2} />
            </g>
          )}

          <path d={areaPath} fill={`url(#${gradId}-fill)`} />
          <path
            d={smoothPath}
            fill="none"
            stroke="#2563eb"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        </svg>

        {hover !== null && hovered && (
          <div
            className="pointer-events-none absolute z-10 -translate-x-1/2 rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 shadow-lg"
            style={{
              left: `${Math.min(90, Math.max(10, (x(hover) / w) * 100))}%`,
              top: `${Math.min(90, Math.max(8, (y(hovered.value) / h) * 100))}%`,
            }}
          >
            <p className="text-[11px] font-medium text-zinc-400">
              {labelFormatter ? labelFormatter(hovered.label) : hovered.label}
            </p>
            <p className="text-sm font-semibold tabular-nums text-zinc-900">
              {valueFormatter(hovered.value)}
            </p>
          </div>
        )}
      </div>
      <div className="mt-1 flex items-center justify-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-blue-600" />
        <span className="text-[11px] text-zinc-400">Hover for details</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* BarList — horizontal progress-bar rows (status breakdown,           */
/* departments). Cleaner than a donut for small categorical datasets.  */
/* ------------------------------------------------------------------ */

export function BarList({
  data,
  formatValue = (v: number) => String(v),
  colorClass = "bg-blue-500",
}: {
  data: Array<{ label: string; value: number; hint?: string }>;
  formatValue?: (v: number) => string;
  colorClass?: string;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div className="space-y-3.5">
      {data.map((d) => (
        <div key={d.label}>
          <div className="mb-1 flex items-baseline justify-between gap-3">
            <span className="truncate text-[13px] font-medium text-zinc-700">{d.label}</span>
            <span className="shrink-0 text-[13px] font-medium tabular-nums text-zinc-900">
              {formatValue(d.value)}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-100">
            <div
              className={`h-full rounded-full ${colorClass} transition-[width] duration-300`}
              style={{ width: `${(d.value / max) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
