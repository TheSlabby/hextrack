/** Small building blocks shared by the Trends tab cards. */
import type { ReactNode } from "react";

import { QueueToggle } from "@/components/leaderboard/QueueToggle";
import { SinceToggle } from "@/components/squad/SinceToggle";
import { cn } from "@/lib/cn";

import type { TrendsFilters } from "./model";

// --- filters ----------------------------------------------------------------------------

export interface TrendsFilterBarProps {
  filters: TrendsFilters;
  onChange: (next: TrendsFilters) => void;
  /** Left-hand caption (e.g. how many games the tab covers). */
  children?: ReactNode;
  className?: string;
}

/**
 * One filter row above every card of the tab: period (season / all time) and ranked queue. Uses
 * the same toggles as Leaderboard, Squad and Records, so the labels read the same everywhere.
 */
export function TrendsFilterBar({ filters, onChange, children, className }: TrendsFilterBarProps) {
  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-x-4 gap-y-2", className)}>
      <div className="min-w-0 text-sm text-text-secondary">{children}</div>
      <div className="flex flex-wrap items-center gap-2">
        <SinceToggle value={filters.since} onChange={(since) => onChange({ ...filters, since })} />
        <QueueToggle value={filters.queue} onChange={(queue) => onChange({ ...filters, queue })} />
      </div>
    </div>
  );
}

// --- refetch dimming --------------------------------------------------------------------

/** Keeps the previous result on screen at reduced opacity while a new filter loads. */
export function Refetching({ active, children, className }: { active: boolean; children: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0 transition-opacity duration-200", active && "opacity-60", className)} aria-busy={active}>
      {children}
    </div>
  );
}

// --- inline figures ---------------------------------------------------------------------

/** Label, figure and caption inside a surface-2 panel (smaller than a StatTile). */
export function FigurePanel({
  label,
  value,
  caption,
  muted,
  className,
  children,
}: {
  label: ReactNode;
  value: ReactNode;
  caption?: ReactNode;
  /** Greyed out: the sample is below the minimum. */
  muted?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1 rounded-xl border border-border bg-surface-2/50 p-3", className)}>
      <span className="label-caps truncate">{label}</span>
      <span
        className={cn(
          "font-display text-xl leading-7 font-semibold tabular-nums",
          muted ? "text-text-muted" : "text-text",
        )}
      >
        {value}
      </span>
      {caption ? <span className="text-xs text-text-muted">{caption}</span> : null}
      {children}
    </div>
  );
}
