/** Building blocks for the grid tooltips: the value leads, labels follow (web/DESIGN.md → Charts). */
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export function DetailTitle({ children }: { children: ReactNode }) {
  return <div className="mb-1.5 truncate font-medium text-text-secondary">{children}</div>;
}

/** Headline figure: big value, then what it is. */
export function DetailHeadline({ value, children }: { value: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="font-display text-lg leading-6 font-bold text-text tabular-nums">{value}</span>
      <span className="text-text-secondary">{children}</span>
    </div>
  );
}

export function DetailRows({ children }: { children: ReactNode }) {
  return <dl className="mt-2 grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 border-t border-border pt-2">{children}</dl>;
}

export function DetailRow({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <>
      <dt className="text-text-secondary">{label}</dt>
      <dd className="text-right font-semibold text-text tabular-nums">{children}</dd>
    </>
  );
}

export function DetailNote({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("mt-2 text-[11px] leading-snug text-text-muted", className)}>{children}</p>;
}

/** "12W 8L" with the outcome colours on the letters' numbers. */
export function WinLoss({ wins, losses }: { wins: number; losses: number }) {
  return (
    <span className="tabular-nums">
      <span className="text-win">{wins}W</span> <span className="text-loss">{losses}L</span>
    </span>
  );
}

/** Two-line matrix cell body: the value, then a small caption under it. */
export function TwoLine({ top, bottom }: { top: string; bottom: string }) {
  return (
    <>
      <span className="text-[13px] font-semibold">{top}</span>
      <span className="text-[10px]">{bottom}</span>
    </>
  );
}
