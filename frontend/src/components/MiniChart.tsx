"use client";

import React from "react";

export interface ChartSeries {
  points: Array<[number, number]>;
  color: string;
  width?: number;
  dash?: string;
  /** Fill the area under the curve down to y = 0. */
  fill?: boolean;
  opacity?: number;
}

export interface ChartMarker {
  x: number;
  y: number;
  color: string;
  label?: string;
}

interface MiniChartProps {
  series: ChartSeries[];
  markers?: ChartMarker[];
  xLabel?: string;
  yLabel?: string;
  height?: number;
  /** Same scale on both axes (maps). */
  equal?: boolean;
  /** Logarithmic x axis (x values must be positive). */
  xLog?: boolean;
  /** Force the y axis to start at 0. */
  yZero?: boolean;
  ariaLabel: string;
}

const W = 520;
const PAD = { l: 48, r: 14, t: 10, b: 36 };

function niceTicks(lo: number, hi: number, n = 5): number[] {
  const span = hi - lo;
  if (!(span > 0) || !Number.isFinite(span)) return [lo];
  const raw = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + step * 1e-9; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

function label(v: number): string {
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1000 || a < 0.01) return v.toExponential(0);
  return String(Number(v.toPrecision(3)));
}

/** Small dependency-free line chart in the panel's own colours. */
export function MiniChart({
  series,
  markers = [],
  xLabel,
  yLabel,
  height = 220,
  equal = false,
  xLog = false,
  yZero = false,
  ariaLabel,
}: MiniChartProps) {
  const tx = (x: number) => (xLog ? Math.log10(x) : x);
  const xs: number[] = [];
  const ys: number[] = [];
  for (const s of series) {
    for (const [x, y] of s.points) {
      if (Number.isFinite(x) && Number.isFinite(y) && (!xLog || x > 0)) {
        xs.push(tx(x));
        ys.push(y);
      }
    }
  }
  for (const m of markers) {
    if (Number.isFinite(m.x) && Number.isFinite(m.y) && (!xLog || m.x > 0)) {
      xs.push(tx(m.x));
      ys.push(m.y);
    }
  }
  if (xs.length < 2) return null;

  let x0 = Math.min(...xs);
  let x1 = Math.max(...xs);
  let y0 = yZero ? Math.min(0, ...ys) : Math.min(...ys);
  let y1 = Math.max(...ys);
  if (x1 === x0) {
    x0 -= 1;
    x1 += 1;
  }
  if (y1 === y0) {
    y0 -= 1;
    y1 += 1;
  }
  const padY = (y1 - y0) * 0.06;
  y1 += padY;
  if (!yZero) y0 -= padY;

  const plotW = W - PAD.l - PAD.r;
  const plotH = height - PAD.t - PAD.b;
  if (equal) {
    const scale = Math.min(plotW / (x1 - x0), plotH / (y1 - y0));
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    x0 = cx - plotW / scale / 2;
    x1 = cx + plotW / scale / 2;
    y0 = cy - plotH / scale / 2;
    y1 = cy + plotH / scale / 2;
  }
  const px = (x: number) => PAD.l + ((tx(x) - x0) / (x1 - x0)) * plotW;
  const py = (y: number) => PAD.t + (1 - (y - y0) / (y1 - y0)) * plotH;

  const xTicks: Array<{ at: number; text: string }> = [];
  if (xLog) {
    for (let e = Math.ceil(x0 - 1e-9); e <= Math.floor(x1 + 1e-9); e += 1) {
      xTicks.push({ at: PAD.l + ((e - x0) / (x1 - x0)) * plotW, text: label(Math.pow(10, e)) });
    }
  } else {
    for (const v of niceTicks(x0, x1)) xTicks.push({ at: PAD.l + ((v - x0) / (x1 - x0)) * plotW, text: label(v) });
  }
  const yTicks = niceTicks(y0, y1, 4).map((v) => ({ at: py(v), text: label(v) }));

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="h-auto w-full" role="img" aria-label={ariaLabel}>
      {yTicks.map((t, i) => (
        <g key={`y${i}`}>
          <line x1={PAD.l} x2={W - PAD.r} y1={t.at} y2={t.at} stroke="rgba(255,255,255,0.07)" />
          <text x={PAD.l - 6} y={t.at + 3.5} textAnchor="end" fontSize="10" fill="#8e877f">
            {t.text}
          </text>
        </g>
      ))}
      {xTicks.map((t, i) => (
        <g key={`x${i}`}>
          <line x1={t.at} x2={t.at} y1={PAD.t} y2={height - PAD.b} stroke="rgba(255,255,255,0.07)" />
          <text x={t.at} y={height - PAD.b + 13} textAnchor="middle" fontSize="10" fill="#8e877f">
            {t.text}
          </text>
        </g>
      ))}
      {series.map((s, i) => {
        const pts = s.points.filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y) && (!xLog || x > 0));
        if (pts.length < 2) return null;
        const line = pts.map(([x, y]) => `${px(x).toFixed(1)},${py(y).toFixed(1)}`).join(" ");
        const base = py(Math.max(0, y0)).toFixed(1);
        const area = `${px(pts[0][0]).toFixed(1)},${base} ${line} ${px(pts[pts.length - 1][0]).toFixed(1)},${base}`;
        return (
          <g key={`s${i}`} opacity={s.opacity ?? 1}>
            {s.fill && <polygon points={area} fill={s.color} opacity={0.16} />}
            <polyline
              points={line}
              fill="none"
              stroke={s.color}
              strokeWidth={s.width ?? 1.6}
              strokeDasharray={s.dash}
              strokeLinejoin="round"
            />
          </g>
        );
      })}
      {markers.map((m, i) => (
        <g key={`m${i}`}>
          <circle cx={px(m.x)} cy={py(m.y)} r={3.4} fill={m.color} stroke="#050506" strokeWidth={1} />
          {m.label && (
            <text x={px(m.x) + 7} y={py(m.y) + 3.5} fontSize="10" fill="#c2bbb3">
              {m.label}
            </text>
          )}
        </g>
      ))}
      {xLabel && (
        <text x={PAD.l + plotW / 2} y={height - 5} textAnchor="middle" fontSize="10.5" fill="#c2bbb3">
          {xLabel}
        </text>
      )}
      {yLabel && (
        <text
          x={12}
          y={PAD.t + plotH / 2}
          textAnchor="middle"
          fontSize="10.5"
          fill="#c2bbb3"
          transform={`rotate(-90 12 ${PAD.t + plotH / 2})`}
        >
          {yLabel}
        </text>
      )}
    </svg>
  );
}
