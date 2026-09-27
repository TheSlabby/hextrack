import { Fragment, type ReactNode } from "react";
import { ChevronRight, Clock } from "lucide-react";

import type { BuildOption } from "@/api/types";
import { cn } from "@/lib/cn";
import { formatCompact, plural } from "@/lib/format";

import { buildTime, pct, winRateTone } from "./detailModel";
import { ItemIcon } from "./ItemIcon";

/** Anything with a win / pick rate: build, rune page, spell pair, max order, item. */
export interface OptionNumbers {
  games: number;
  win_rate: number;
  pick_rate: number;
}

/** The two right-hand columns of an option row: win rate and pick rate (games under the pick). */
export function OptionStats({ option, className }: { option: OptionNumbers; className?: string }) {
  return (
    <div className={cn("flex shrink-0 items-center gap-3 text-right tabular-nums", className)}>
      <span className={cn("w-12 text-sm font-semibold", winRateTone(option.win_rate))}>{pct(option.win_rate)}</span>
      <span className="flex w-12 flex-col leading-tight" title={plural(option.games, "game")}>
        <span className="text-sm text-text-secondary">{pct(option.pick_rate)}</span>
        <span className="text-[10px] text-text-muted">{formatCompact(option.games)}</span>
      </span>
    </div>
  );
}

/** Column labels above a list of option rows, lined up with `OptionStats`. */
export function OptionListHeader({ label, className }: { label: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-end justify-between gap-3 px-2.5", className)}>
      <span className="label-caps truncate">{label}</span>
      <span className="flex shrink-0 gap-3 text-right">
        <span className="label-caps w-12">Win</span>
        <span className="label-caps w-12">Pick</span>
      </span>
    </div>
  );
}

/** One row of a list: content on the left, win / pick on the right. `highlight` = the top pick. */
export function OptionRow({
  option,
  children,
  highlight,
  className,
}: {
  option: OptionNumbers;
  children: ReactNode;
  highlight?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex min-w-0 items-center justify-between gap-3 rounded-lg border px-2.5 py-1.5",
        highlight ? "border-gold/25 bg-gold/[0.05]" : "border-transparent bg-white/[0.025]",
        className,
      )}
    >
      <div className="flex min-w-0 items-center gap-2">{children}</div>
      <OptionStats option={option} />
    </div>
  );
}

/** Item icons in order with chevrons between them. */
export function ItemPath({
  items,
  size = 32,
  arrows = true,
  className,
}: {
  items: readonly number[];
  size?: number;
  /** Chevrons between items (off for sets bought together, like starting items). */
  arrows?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-wrap items-center", arrows ? "gap-0.5" : "gap-1", className)}>
      {items.map((id, i) => (
        <Fragment key={`${id}-${i}`}>
          {arrows && i > 0 ? <ChevronRight className="size-3.5 shrink-0 text-text-muted" aria-hidden="true" /> : null}
          <ItemIcon id={id} size={size} />
        </Fragment>
      ))}
    </div>
  );
}

export interface BuildPathRowProps {
  option: BuildOption;
  /** Show the average time the build was done (core builds). */
  showTime?: boolean;
  arrows?: boolean;
  /** A small label next to the items, e.g. "Highest win rate". */
  badge?: ReactNode;
  highlight?: boolean;
  className?: string;
}

/** One build option: its items (in order) on the left, win and pick rate on the right. */
export function BuildPathRow({ option, showTime, arrows = true, badge, highlight, className }: BuildPathRowProps) {
  const time = showTime ? buildTime(option.avg_time_s) : null;
  return (
    <OptionRow option={option} highlight={highlight} className={className}>
      <ItemPath items={option.items} size={26} arrows={arrows} />
      {badge || time ? (
        <span className="hidden min-w-0 flex-col text-[11px] leading-tight text-text-muted sm:flex">
          {badge}
          {time ? (
            <span className="inline-flex items-center gap-1 tabular-nums" title={`Done ${time} into the game on average`}>
              <Clock className="size-3" aria-hidden="true" />
              {time}
            </span>
          ) : null}
        </span>
      ) : null}
    </OptionRow>
  );
}
