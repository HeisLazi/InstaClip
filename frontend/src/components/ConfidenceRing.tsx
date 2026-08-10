/**
 * Color-mapped circular probability gauge.
 *
 * Per the redesign doc (Section 9):
 *   ≥90%  vibrant emerald — high certainty
 *   60-89% amber/yellow   — verify
 *   <60%  muted gray/red  — uncertain
 *
 * Renders an SVG ring with a centre number. Size is tunable.
 */

import { cn } from "@/lib/utils";

interface ConfidenceRingProps {
  /** 0-1 (probability) or 0-100 (percent). Auto-detected by magnitude. */
  value: number | null | undefined;
  /** Display size in px. */
  size?: number;
  /** Stroke width. */
  stroke?: number;
  /** Tooltip text. */
  title?: string;
  /** Optional override label shown under the value. */
  caption?: string;
  className?: string;
}

function classifyPercent(p: number): "high" | "med" | "low" {
  if (p >= 90) return "high";
  if (p >= 60) return "med";
  return "low";
}

const TONE = {
  high: { stroke: "hsl(var(--success))",     text: "text-success" },
  med:  { stroke: "hsl(var(--warning))",     text: "text-warning" },
  low:  { stroke: "hsl(var(--destructive))", text: "text-destructive" },
};

export function ConfidenceRing({
  value, size = 56, stroke = 6, title, caption, className,
}: ConfidenceRingProps) {
  if (value == null || isNaN(value)) {
    return (
      <div
        className={cn("inline-flex items-center justify-center text-[10px] text-muted-foreground", className)}
        style={{ width: size, height: size }}
        title={title ?? "no score"}
      >
        —
      </div>
    );
  }

  // Accept either 0-1 or 0-100; clamp to [0, 100].
  const pct = Math.max(0, Math.min(100, value <= 1 ? value * 100 : value));
  const tier = classifyPercent(pct);
  const { stroke: strokeColor, text: textClass } = TONE[tier];

  const r          = (size - stroke) / 2;
  const c          = 2 * Math.PI * r;
  const dashOffset = c * (1 - pct / 100);

  return (
    <div
      className={cn("relative inline-flex items-center justify-center select-none", className)}
      style={{ width: size, height: size }}
      title={title ?? `${pct.toFixed(0)}%`}
    >
      <svg width={size} height={size} className="-rotate-90">
        {/* Track */}
        <circle
          cx={size / 2} cy={size / 2} r={r}
          stroke="hsl(var(--secondary))"
          strokeWidth={stroke}
          fill="none"
        />
        {/* Arc */}
        <circle
          cx={size / 2} cy={size / 2} r={r}
          stroke={strokeColor}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={dashOffset}
          style={{ transition: "stroke-dashoffset 300ms ease-out" }}
        />
      </svg>
      <div className={cn(
        "absolute inset-0 flex flex-col items-center justify-center leading-none",
        textClass,
      )}>
        <span className="text-[13px] font-semibold tabular-nums">{pct.toFixed(0)}</span>
        {caption ? (
          <span className="text-[8px] uppercase tracking-wider text-muted-foreground mt-0.5">
            {caption}
          </span>
        ) : (
          <span className="text-[8px] text-muted-foreground/70">%</span>
        )}
      </div>
    </div>
  );
}
