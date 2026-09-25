import { cn } from "@/lib/cn";

import { LiveDot } from "./LiveDot";

/** Small live dot next to a roster player's name while they're in a game (with a label for screen readers). */
export function InGameDot({ live, className }: { live: boolean; className?: string }) {
  if (!live) return null;
  return (
    <span className={cn("inline-flex items-center", className)} title="In a game right now">
      <LiveDot size="sm" showLabel={false} />
      <span className="sr-only">(in a game right now)</span>
    </span>
  );
}
