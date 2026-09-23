import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

import { SELF_CELL_CLASS } from "./PlayerMatrix";
import { BINS, binColor, type Arm } from "./scale";

const SWATCH_PX = 28;
const GAP_PX = 2;

export interface BinLegendProps {
  /** What the colour measures, e.g. "Win rate together vs expected". */
  title: string;
  arm: Arm;
  /** Labels for the six boundaries between the seven bins, left to right. */
  ticks: readonly [string, string, string, string, string, string];
  lowLabel: string;
  highLabel: string;
  className?: string;
}

/** Legend for a binned diverging scale: seven swatches, boundary ticks, and the two ends named. */
export function BinLegend({ title, arm, ticks, lowLabel, highLabel, className }: BinLegendProps) {
  const width = BINS.length * SWATCH_PX + (BINS.length - 1) * GAP_PX;
  return (
    <figure className={cn("flex flex-col gap-1.5", className)} aria-label={`${title}: ${lowLabel} to ${highLabel}`}>
      <figcaption className="text-xs font-medium text-text-secondary">{title}</figcaption>
      <div className="flex flex-col gap-0.5" style={{ width }} aria-hidden="true">
        <div className="flex" style={{ gap: GAP_PX }}>
          {BINS.map((bin) => (
            <span
              key={bin}
              className="h-2.5 rounded-[3px]"
              style={{ width: SWATCH_PX, backgroundColor: binColor(bin, arm) }}
            />
          ))}
        </div>
        <div className="relative h-4 text-[10px] leading-4 text-text-muted tabular-nums">
          {ticks.map((tick, index) => (
            <span
              key={tick}
              className="absolute top-0 -translate-x-1/2"
              style={{ left: (index + 1) * (SWATCH_PX + GAP_PX) - GAP_PX / 2 }}
            >
              {tick}
            </span>
          ))}
        </div>
        <div className="flex justify-between text-[11px] leading-4 text-text-secondary">
          <span>← {lowLabel}</span>
          <span>{highLabel} →</span>
        </div>
      </div>
    </figure>
  );
}

/** A small sample cell plus its meaning, for the non-colour cell kinds (diagonal, small samples). */
export function CellKey({ sample, children, className }: { sample: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2 text-[11px] leading-4 text-text-secondary", className)}>
      <span aria-hidden="true" className="flex h-6 w-9 shrink-0 items-center justify-center rounded text-[10px] tabular-nums">
        {sample}
      </span>
      <span>{children}</span>
    </div>
  );
}

/** Sample for the diagonal key. */
export function SelfSample({ children }: { children: ReactNode }) {
  return (
    <span className={cn("flex size-full items-center justify-center rounded", SELF_CELL_CLASS)}>{children}</span>
  );
}

/** Sample for the small-sample key. */
export function MutedSample({ children }: { children: ReactNode }) {
  return (
    <span className="flex size-full items-center justify-center rounded bg-white/[0.025] text-text-muted">{children}</span>
  );
}
