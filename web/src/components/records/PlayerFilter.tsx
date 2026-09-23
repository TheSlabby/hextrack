/** Player chips for /records: "Everyone" (the roster) or one player's own records. */
import { Users } from "lucide-react";

import { ProfileIcon } from "@/components/common/ProfileIcon";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";

export interface PlayerChip {
  puuid: string;
  /** Chip text: the game name, plus the tag when two players share it. */
  label: string;
  /** Full Riot ID for the tooltip ("sam#gjoat"). */
  riotId: string;
  iconId: number | null;
}

export interface PlayerFilterProps {
  players: readonly PlayerChip[];
  /** Selected puuid; null = everyone. */
  selected: string | null;
  onSelect: (puuid: string | null) => void;
  loading?: boolean;
  className?: string;
}

const CHIP = cn(
  "inline-flex h-8 shrink-0 items-center gap-2 rounded-full border pr-3 text-xs font-medium whitespace-nowrap",
  "transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
);
const CHIP_IDLE = "border-border bg-surface-1 text-text-secondary hover:border-border-strong hover:text-text";
const CHIP_ACTIVE = "border-gold/50 bg-gold/12 text-gold-bright";

/**
 * On phones the chips scroll sideways inside a full-bleed strip (the page itself never
 * scrolls horizontally); from sm up they wrap.
 */
export function PlayerFilter({ players, selected, onSelect, loading, className }: PlayerFilterProps) {
  return (
    <div
      role="group"
      aria-label="Show records for"
      className={cn(
        "scrollbar-thin -mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 sm:pb-0",
        className,
      )}
    >
      <button
        type="button"
        aria-pressed={selected === null}
        onClick={() => onSelect(null)}
        className={cn(CHIP, "pl-2.5", selected === null ? CHIP_ACTIVE : CHIP_IDLE)}
      >
        <Users className="size-3.5" aria-hidden="true" />
        Everyone
      </button>
      {loading
        ? Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-8 w-28 shrink-0 rounded-full" />)
        : players.map((player) => {
            const active = player.puuid === selected;
            return (
              <button
                key={player.puuid}
                type="button"
                aria-pressed={active}
                title={player.riotId}
                onClick={() => onSelect(active ? null : player.puuid)}
                className={cn(CHIP, "pl-1", active ? CHIP_ACTIVE : CHIP_IDLE)}
              >
                <ProfileIcon iconId={player.iconId} size="xs" alt="" />
                {player.label}
              </button>
            );
          })}
    </div>
  );
}
