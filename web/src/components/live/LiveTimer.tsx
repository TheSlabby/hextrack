import type { LiveGame } from "@/api/types";
import { useNow } from "@/components/summoner/hooks";
import { cn } from "@/lib/cn";

import { formatLiveClock, liveElapsedSeconds } from "./model";

export interface LiveTimerProps {
  game: Pick<LiveGame, "started_at">;
  className?: string;
}

/** "12 minutes in", "1 hour 4 minutes in"; for screen readers, which shouldn't hear every second. */
function spokenElapsed(seconds: number | null): string {
  if (seconds === null) return "Game loading";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h === 0 && m === 0) return "Under a minute in";
  const parts = [
    h > 0 ? `${h} ${h === 1 ? "hour" : "hours"}` : null,
    m > 0 ? `${m} ${m === 1 ? "minute" : "minutes"}` : null,
  ].filter(Boolean);
  return `${parts.join(" ")} in`;
}

/** Ticking in-game clock ("23:05", "Loading" before the game starts). */
export function LiveTimer({ game, className }: LiveTimerProps) {
  const now = useNow(1000);
  const seconds = liveElapsedSeconds(game, now);
  return (
    <span role="timer" aria-label={spokenElapsed(seconds)} className={cn("tabular-nums", className)}>
      {formatLiveClock(seconds)}
    </span>
  );
}
