import type { StackQueue } from "@/api/types";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/cn";

import { STACK_QUEUE_LABEL } from "./model";

const OPTIONS: ReadonlyArray<{ value: StackQueue; label: string; title: string }> = [
  { value: "all", label: STACK_QUEUE_LABEL.all, title: "Every queue the squad stacked in" },
  { value: "flex", label: STACK_QUEUE_LABEL.flex, title: "Ranked Flex only" },
];

function isStackQueue(value: string): value is StackQueue {
  return OPTIONS.some((option) => option.value === value);
}

/** Segmented All queues / Ranked Flex filter for the Stacks page. */
export function StackQueueToggle({
  value,
  onChange,
  className,
}: {
  value: StackQueue;
  onChange: (queue: StackQueue) => void;
  className?: string;
}) {
  return (
    <ToggleGroup
      type="single"
      size="sm"
      value={value}
      onValueChange={(next) => {
        // Radix allows deselecting the active item; keep one queue selected at all times.
        if (next && isStackQueue(next)) onChange(next);
      }}
      aria-label="Queue"
      className={cn(className)}
    >
      {OPTIONS.map((option) => (
        <ToggleGroupItem key={option.value} value={option.value} title={option.title}>
          {option.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
