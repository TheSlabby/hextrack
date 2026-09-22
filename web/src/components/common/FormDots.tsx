import { cn } from "@/lib/cn";

export interface FormDotsProps {
  /** Results, newest first (true = win). */
  results: readonly boolean[];
  /** Max results to show. */
  limit?: number;
  size?: "sm" | "md";
  className?: string;
}

/**
 * Recent form strip, newest on the left. `md` shows W/L letters in the chips; `sm` shows
 * compact bars. Either way the full sequence is available as text to screen readers.
 */
export function FormDots({ results, limit = 20, size = "md", className }: FormDotsProps) {
  const shown = results.slice(0, limit);
  const wins = shown.filter(Boolean).length;
  const label = shown.length
    ? `Recent form, newest first: ${shown.map((w) => (w ? "W" : "L")).join(" ")} (${wins}W ${shown.length - wins}L)`
    : "No recent games";

  if (shown.length === 0) {
    // A dash keeps narrow columns intact; the sentence stays for screen readers.
    return (
      <span className={cn("text-xs text-text-muted", className)}>
        <span aria-hidden="true">–</span>
        <span className="sr-only">No recent games</span>
      </span>
    );
  }

  return (
    <div className={cn("flex flex-wrap items-center", size === "md" ? "gap-1" : "gap-0.5", className)} role="img" aria-label={label}>
      {shown.map((win, i) =>
        size === "md" ? (
          <span
            key={i}
            aria-hidden="true"
            className={cn(
              "flex size-5 items-center justify-center rounded-[5px] text-[10px] font-bold",
              win ? "bg-win/15 text-win" : "bg-loss/15 text-loss",
            )}
          >
            {win ? "W" : "L"}
          </span>
        ) : (
          <span
            key={i}
            aria-hidden="true"
            title={win ? "Win" : "Loss"}
            className={cn("h-3.5 w-1.5 rounded-full", win ? "bg-win" : "bg-loss/80")}
          />
        ),
      )}
    </div>
  );
}
