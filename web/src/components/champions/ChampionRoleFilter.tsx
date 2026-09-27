import type { ChampionRole } from "@/api/types";
import { PositionIcon } from "@/components/common/PositionIcon";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/cn";
import { POSITION_LONG_LABELS } from "@/lib/positions";

const ROLES: readonly ChampionRole[] = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"];
const ALL = "all";

/** Segmented All / Top / Jungle / Mid / Bot / Support filter (role icons, labelled). */
export function ChampionRoleFilter({
  value,
  onChange,
  className,
}: {
  value: ChampionRole | null;
  onChange: (role: ChampionRole | null) => void;
  className?: string;
}) {
  return (
    <ToggleGroup
      type="single"
      size="sm"
      value={value ?? ALL}
      onValueChange={(next) => {
        // Radix allows deselecting the active item; keep one option selected at all times.
        if (!next) return;
        onChange(next === ALL ? null : ((ROLES as readonly string[]).includes(next) ? (next as ChampionRole) : null));
      }}
      aria-label="Role"
      className={cn(className)}
    >
      <ToggleGroupItem value={ALL} title="Every role">
        All
      </ToggleGroupItem>
      {ROLES.map((role) => (
        <ToggleGroupItem key={role} value={role} aria-label={POSITION_LONG_LABELS[role]} title={POSITION_LONG_LABELS[role]}>
          <PositionIcon position={role} size={16} title="" />
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
