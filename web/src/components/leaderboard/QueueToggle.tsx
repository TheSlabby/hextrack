import type { LeaderboardQueue } from "@/api/types";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/cn";

const QUEUES: ReadonlyArray<{ value: LeaderboardQueue; label: string; title: string }> = [
  { value: "all", label: "All", title: "Solo/Duo and Flex games" },
  { value: "solo", label: "Solo/Duo", title: "Ranked Solo/Duo only" },
  { value: "flex", label: "Flex", title: "Ranked Flex only" },
];

function isQueue(value: string): value is LeaderboardQueue {
  return QUEUES.some((queue) => queue.value === value);
}

/** Segmented All / Solo / Flex filter for leaderboard stats. */
export function QueueToggle({
  value,
  onChange,
  className,
}: {
  value: LeaderboardQueue;
  onChange: (queue: LeaderboardQueue) => void;
  className?: string;
}) {
  return (
    <ToggleGroup
      type="single"
      size="sm"
      value={value}
      onValueChange={(next) => {
        // Radix allows deselecting the active item; keep one queue selected at all times.
        if (next && isQueue(next)) onChange(next);
      }}
      aria-label="Queue"
      className={cn(className)}
    >
      {QUEUES.map((queue) => (
        <ToggleGroupItem key={queue.value} value={queue.value} title={queue.title}>
          {queue.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
