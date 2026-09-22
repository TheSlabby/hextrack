import { cn } from "@/lib/cn";
import { formatPercent } from "@/lib/format";

export interface WinRateBarProps {
  wins: number;
  losses: number;
  /** Show "12W 8L" and the percentage. */
  showLabels?: boolean;
  size?: "sm" | "md";
  className?: string;
}

/** Split bar: wins (blue) | losses (red), separated by a 2px surface gap, with a text readout. */
export function WinRateBar({ wins, losses, showLabels = true, size = "md", className }: WinRateBarProps) {
  const games = wins + losses;
  const rate = games > 0 ? wins / games : 0;
  const height = size === "sm" ? "h-1.5" : "h-2";
  const label = `${wins} wins, ${losses} losses, ${formatPercent(rate)} win rate`;

  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      {showLabels ? (
        <div className="flex items-baseline justify-between gap-2 text-xs tabular-nums">
          <span className="text-text-secondary">
            <span className="text-win">{wins}W</span> <span className="text-loss">{losses}L</span>
          </span>
          <span className={cn("font-semibold", rate >= 0.5 ? "text-text" : "text-text-secondary")}>
            {games > 0 ? formatPercent(rate) : "–"}
          </span>
        </div>
      ) : null}
      <div className={cn("flex w-full gap-0.5 overflow-hidden rounded-full", height)} role="img" aria-label={label}>
        {games === 0 ? (
          <span className="h-full w-full rounded-full bg-white/6" />
        ) : (
          <>
            {wins > 0 ? <span className="h-full rounded-l-full bg-win" style={{ width: `${rate * 100}%` }} /> : null}
            {losses > 0 ? <span className="h-full flex-1 rounded-r-full bg-loss/85" /> : null}
          </>
        )}
      </div>
    </div>
  );
}
