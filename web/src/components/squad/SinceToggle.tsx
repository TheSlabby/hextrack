import type { StatsSince } from "@/api/types";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/cn";

const OPTIONS: ReadonlyArray<{ value: StatsSince; label: string; title: string }> = [
  { value: "season", label: "Season", title: "Games since the season started" },
  { value: "all", label: "All time", title: "Every stored ranked game" },
];

function isSince(value: string): value is StatsSince {
  return OPTIONS.some((option) => option.value === value);
}

/** Segmented This season / All time filter. */
export function SinceToggle({
  value,
  onChange,
  className,
}: {
  value: StatsSince;
  onChange: (since: StatsSince) => void;
  className?: string;
}) {
  return (
    <ToggleGroup
      type="single"
      size="sm"
      value={value}
      onValueChange={(next) => {
        // Radix allows deselecting the active item; keep one period selected at all times.
        if (next && isSince(next)) onChange(next);
      }}
      aria-label="Period"
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
