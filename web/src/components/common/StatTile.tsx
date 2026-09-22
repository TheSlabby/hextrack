import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";

import { cn } from "@/lib/cn";

import { CountUp } from "./CountUp";
import { GlowCard } from "./GlowCard";

export interface StatDelta {
  value: number;
  /** Formats the delta magnitude (sign is added for you). Default: integer. */
  format?: (value: number) => string;
  /** Whether a positive delta is good (green) or bad (red). Default true. */
  positiveIsGood?: boolean;
  /** What the delta compares against, e.g. "since season start". */
  label?: string;
}

export interface StatTileProps {
  label: string;
  /** Numeric value (formatted with `format`) or any pre-formatted node. */
  value: number | ReactNode;
  /** Formatter for numeric values (also applied during a count-up). */
  format?: (value: number) => string;
  caption?: ReactNode;
  delta?: StatDelta | null;
  icon?: LucideIcon;
  /** Accent for the value: default text, gold, cyan (AI) or a CSS colour. */
  accent?: "default" | "gold" | "cyan" | (string & {});
  /** Render without its own card (inside another card). */
  bare?: boolean;
  /**
   * Count the value up on first paint. Off by default: count-ups are for hero figures, not for
   * every tile (see web/DESIGN.md → Motion).
   */
  animate?: boolean;
  className?: string;
}

const ACCENT_CLASS: Record<string, string> = {
  default: "text-text",
  gold: "text-gold-bright",
  cyan: "text-cyan",
};

function DeltaChip({ delta }: { delta: StatDelta }) {
  const good = delta.positiveIsGood ?? true;
  const sign = Math.sign(delta.value);
  const tone = sign === 0 ? "text-text-muted" : (sign > 0) === good ? "text-score-a" : "text-loss";
  const Icon = sign > 0 ? ArrowUpRight : sign < 0 ? ArrowDownRight : Minus;
  const text = (delta.format ?? ((v: number) => Math.round(v).toString()))(Math.abs(delta.value));
  return (
    <span className={cn("inline-flex items-center gap-0.5 text-xs font-semibold tabular-nums", tone)}>
      <Icon className="size-3.5" aria-hidden="true" />
      <span>
        {sign > 0 ? "+" : sign < 0 ? "−" : ""}
        {text}
      </span>
      {delta.label ? <span className="ml-1 font-normal text-text-muted">{delta.label}</span> : null}
    </span>
  );
}

/** Label + big value (optionally counted up) + caption + optional signed delta. */
export function StatTile({
  label,
  value,
  format,
  caption,
  delta,
  icon: Icon,
  accent = "default",
  bare,
  animate = false,
  className,
}: StatTileProps) {
  const accentClass = ACCENT_CLASS[accent];
  const body = (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex items-center gap-1.5">
        {Icon ? <Icon className="size-3.5 text-text-muted" aria-hidden="true" /> : null}
        <span className="label-caps truncate">{label}</span>
      </div>
      <div
        className={cn("font-display text-2xl leading-tight font-semibold tabular-nums sm:text-[28px]", accentClass)}
        style={accentClass ? undefined : { color: accent }}
      >
        {typeof value === "number" ? (
          animate ? (
            <CountUp value={value} format={format} />
          ) : (
            (format ?? ((v: number) => Math.round(v).toString()))(value)
          )
        ) : (
          value
        )}
      </div>
      {caption || delta ? (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-text-secondary">
          {delta ? <DeltaChip delta={delta} /> : null}
          {caption ? <span className="truncate">{caption}</span> : null}
        </div>
      ) : null}
    </div>
  );
  if (bare) return <div className={className}>{body}</div>;
  return <GlowCard className={cn("p-4", className)}>{body}</GlowCard>;
}
