import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/cn";

import { HISTORY_QUEUE_FILTERS, type HistoryQueueFilterId } from "./matchUtils";

function isFilterId(value: string): value is HistoryQueueFilterId {
  return HISTORY_QUEUE_FILTERS.some((filter) => filter.id === value);
}

export interface QueueFilterProps {
  value: HistoryQueueFilterId;
  onChange: (filter: HistoryQueueFilterId) => void;
  className?: string;
}

/** Single-select queue chips (All / Ranked Solo / Ranked Flex / Normal / ARAM). */
export function QueueFilter({ value, onChange, className }: QueueFilterProps) {
  return (
    <ToggleGroup
      type="single"
      size="sm"
      value={value}
      onValueChange={(next) => {
        // Radix allows deselecting the active chip; keep one selected.
        if (next && isFilterId(next)) onChange(next);
      }}
      aria-label="Filter by queue"
      className={cn("max-w-full overflow-x-auto scrollbar-thin", className)}
    >
      {HISTORY_QUEUE_FILTERS.map((filter) => (
        <ToggleGroupItem
          key={filter.id}
          value={filter.id}
          aria-label={filter.description}
          title={filter.description}
          className="px-2.5 @md:px-3"
        >
          <span className="@lg:hidden">{filter.short}</span>
          <span className="hidden @lg:inline">{filter.label}</span>
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
