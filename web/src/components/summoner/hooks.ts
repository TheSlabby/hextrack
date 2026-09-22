/** Small React hooks used by the summoner page (clock and countdown). */
import { useEffect, useState } from "react";

/**
 * Current time in ms, re-read every `intervalMs` while `enabled`. The clock is read in timers
 * (never during render) so components stay pure; the first tick fires right away so a
 * re-enabled clock never shows a stale value for a whole interval.
 */
export function useNow(intervalMs: number, enabled = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const tick = () => setNow(Date.now());
    const first = window.setTimeout(tick, 0);
    const id = window.setInterval(tick, intervalMs);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(id);
    };
  }, [intervalMs, enabled]);
  return now;
}

/** Whole seconds until `targetMs` (0 once reached or without a target), ticking every second. */
export function useCountdown(targetMs: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (targetMs === null) return;
    let id = 0;
    const tick = () => {
      const current = Date.now();
      setNow(current);
      if (current >= targetMs) window.clearInterval(id);
    };
    const first = window.setTimeout(tick, 0);
    id = window.setInterval(tick, 1_000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(id);
    };
  }, [targetMs]);
  return targetMs === null ? 0 : Math.max(0, Math.ceil((targetMs - now) / 1_000));
}
