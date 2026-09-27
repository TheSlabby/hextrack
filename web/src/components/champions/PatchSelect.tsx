import { useChampionPatches } from "@/api/queries";
import type { ChampionPatchParam } from "@/api/types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { patchWindowLabel } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatInteger } from "@/lib/format";

/**
 * Patch window picker for the champion pages: the two newest patches (default), one patch,
 * or the whole season. Patches come from `useChampionPatches`, newest first.
 */
export function PatchSelect({
  value,
  onChange,
  className,
}: {
  value: ChampionPatchParam;
  onChange: (patch: ChampionPatchParam) => void;
  className?: string;
}) {
  const patches = useChampionPatches();
  const recent = patches.data?.recent ?? [];
  const list = patches.data?.patches ?? [];
  // Keep a patch from the URL selectable even before (or without) the list loading.
  const known =
    value === "recent" ||
    value === "season" ||
    list.some((p) => p.patch === value);

  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        size="sm"
        className={cn("min-w-40", className)}
        aria-label="Patch"
      >
        <SelectValue>{patchWindowLabel(value, recent)}</SelectValue>
      </SelectTrigger>
      <SelectContent position="popper" align="start">
        <SelectItem value="recent">
          {patchWindowLabel("recent", recent)}
        </SelectItem>
        <SelectItem value="season">Whole season</SelectItem>
        {list.length || !known ? <SelectSeparator /> : null}
        {!known ? <SelectItem value={value}>Patch {value}</SelectItem> : null}
        {list.map((p) => (
          <SelectItem key={p.patch} value={p.patch}>
            <span className="flex w-full items-baseline justify-between gap-4">
              <span>Patch {p.patch}</span>
              <span className="text-xs text-text-muted tabular-nums">
                {formatInteger(p.matches)} games
              </span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
