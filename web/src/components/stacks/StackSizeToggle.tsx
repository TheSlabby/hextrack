import type { StackSize } from "@/api/types";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/cn";

const OPTIONS: ReadonlyArray<{ value: StackSize; label: string; title: string }> = [
  { value: 5, label: "5", title: "Full 5-stacks: five tracked players on one team" },
  { value: 4, label: "4+", title: "Four or more tracked players on one team" },
  { value: 3, label: "3+", title: "Three or more tracked players on one team" },
];

function toSize(value: string): StackSize | null {
  return OPTIONS.find((option) => String(option.value) === value)?.value ?? null;
}

/** Segmented 5 / 4+ / 3+ filter: how many tracked players must share a team. */
export function StackSizeToggle({
  value,
  onChange,
  className,
}: {
  value: StackSize;
  onChange: (size: StackSize) => void;
  className?: string;
}) {
  return (
    <ToggleGroup
      type="single"
      size="sm"
      value={String(value)}
      onValueChange={(next) => {
        // Radix allows deselecting the active item; keep one size selected at all times.
        const size = next ? toSize(next) : null;
        if (size) onChange(size);
      }}
      aria-label="Stack size"
      className={cn(className)}
    >
      {OPTIONS.map((option) => (
        <ToggleGroupItem
          key={option.value}
          value={String(option.value)}
          title={option.title}
          aria-label={option.value === 5 ? "5-stacks" : `${option.label} stacks`}
          className="tabular-nums"
        >
          {option.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
