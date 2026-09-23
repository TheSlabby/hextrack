/** The pentakill hall of fame (every pentakill game, newest first) and quadra kill counts. */
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { ChevronDown, Crown, Swords } from "lucide-react";

import type { QuadrakillCount, RecordEntry, RecordScope, StatsSince } from "@/api/types";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { GlowCard } from "@/components/common/GlowCard";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { SectionHeader } from "@/components/common/SectionHeader";
import { playerSearchValue } from "@/components/match/focus";
import { Button } from "@/components/ui/button";
import { championDisplayName } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatDate, formatInteger, plural } from "@/lib/format";
import { useMediaQuery } from "@/lib/hooks";
import { summonerParams } from "@/lib/riotId";

import { formatCompactDate, PERIOD_LABEL, playerLabel, resultLabel, type PlayerLookup } from "./recordMeta";

/** Tiles shown before "Show all": three rows of three (xl) or four rows of two, four on a phone. */
const COLLAPSED = { xl: 9, sm: 8, phone: 4 } as const;

function PentakillTile({ entry, scope, players }: { entry: RecordEntry; scope: RecordScope; players: PlayerLookup }) {
  const champion = championDisplayName(entry.champion_name);
  const count = Math.round(entry.value);
  const label = `${count > 1 ? `${count} pentakills` : "Pentakill"} by ${entry.game_name}#${entry.tag_line} as ${champion}, ${formatDate(entry.game_start)}, ${resultLabel(entry)}. Open match.`;
  return (
    <Link
      to="/match/$matchId"
      params={{ matchId: entry.match_id }}
      search={{ player: playerSearchValue(entry) }}
      aria-label={label}
      className={cn(
        "group/penta flex min-w-0 items-center gap-3 rounded-xl border border-gold/20 bg-gold/[0.04] p-2.5",
        "transition-[border-color,background-color] duration-150 hover:border-gold/45 hover:bg-gold/[0.08]",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
      )}
    >
      <span className="relative shrink-0">
        <ChampionIcon champion={entry.champion_name} size="md" highlight />
        {scope === "roster" ? (
          <ProfileIcon
            iconId={players.get(entry.puuid)?.iconId}
            size="xs"
            alt=""
            className="absolute -right-1.5 -bottom-1.5 scale-90"
          />
        ) : null}
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-sm font-semibold text-text transition-colors group-hover/penta:text-gold-bright">
          {scope === "player" ? champion : playerLabel(players, entry)}
        </span>
        <span className="truncate text-xs text-text-secondary tabular-nums">
          {scope === "player" ? "" : `${champion} · `}
          {formatCompactDate(entry.game_start)}
        </span>
      </span>
      {count > 1 ? (
        <span className="shrink-0 rounded-full border border-gold/40 bg-gold/15 px-1.5 text-[11px] leading-4 font-bold text-gold-bright tabular-nums">
          ×{count}
        </span>
      ) : null}
    </Link>
  );
}

export interface PentakillHallOfFameProps {
  pentakills: readonly RecordEntry[];
  scope: RecordScope;
  since: StatsSince;
  players: PlayerLookup;
  /** One player's quadra kills (that did not become pentakills), shown in the header; the roster
   * view lists them in `QuadrakillList` instead. */
  quadrakills?: number;
  className?: string;
}

/** Every pentakill in the period, newest first; long lists collapse to the latest few. */
export function PentakillHallOfFame({
  pentakills,
  scope,
  since,
  players,
  quadrakills,
  className,
}: PentakillHallOfFameProps) {
  const [expanded, setExpanded] = useState(false);
  const xl = useMediaQuery("(min-width: 1280px)");
  const sm = useMediaQuery("(min-width: 640px)");
  const collapsed = xl ? COLLAPSED.xl : sm ? COLLAPSED.sm : COLLAPSED.phone;
  const total = pentakills.reduce((sum, entry) => sum + Math.round(entry.value), 0);
  const shown = expanded ? pentakills : pentakills.slice(0, collapsed);
  const hidden = pentakills.length - shown.length;

  return (
    <GlowCard glow={pentakills.length > 0 ? "gold" : null} className={cn("flex flex-col gap-4 p-4 sm:p-5", className)}>
      <SectionHeader
        title="Pentakill hall of fame"
        eyebrow={total > 0 ? plural(total, "pentakill") : "Pentakills"}
        icon={Crown}
        description={
          quadrakills === undefined
            ? `Every pentakill ${PERIOD_LABEL[since]}, newest first.`
            : `Every pentakill ${PERIOD_LABEL[since]}, newest first. Plus ${plural(quadrakills, "quadra kill")} that stopped one short.`
        }
      />
      {pentakills.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border-strong px-4 py-6 text-center text-sm text-text-secondary">
          No pentakills {PERIOD_LABEL[since]} yet. The first one gets a spot right here.
        </p>
      ) : (
        <>
          <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3" aria-label="Pentakills">
            {shown.map((entry) => (
              <li key={`${entry.match_id}:${entry.puuid}`} className="min-w-0">
                <PentakillTile entry={entry} scope={scope} players={players} />
              </li>
            ))}
          </ul>
          {pentakills.length > collapsed ? (
            <Button
              variant="ghost"
              size="sm"
              className="w-fit self-center text-gold hover:text-gold-bright"
              onClick={() => setExpanded((open) => !open)}
              aria-expanded={expanded}
            >
              {expanded ? "Show fewer" : `Show all ${plural(pentakills.length, "game")}`}
              <ChevronDown className={cn("transition-transform duration-200", expanded && "rotate-180")} aria-hidden="true" />
              {!expanded && hidden > 0 ? <span className="sr-only">({hidden} more)</span> : null}
            </Button>
          ) : null}
        </>
      )}
    </GlowCard>
  );
}

export interface QuadrakillListProps {
  quadrakills: readonly QuadrakillCount[];
  since: StatsSince;
  players: PlayerLookup;
  className?: string;
}

/** Quadra kill totals per player, most first, with a bar relative to the leader. */
export function QuadrakillList({ quadrakills, since, players, className }: QuadrakillListProps) {
  const max = quadrakills[0]?.count ?? 0;
  return (
    <GlowCard className={cn("flex flex-col gap-4 p-4 sm:p-5", className)}>
      <SectionHeader
        title="Quadra kills"
        eyebrow="So close"
        icon={Swords}
        description={`Quadra kills ${PERIOD_LABEL[since]} that stopped one short (pentakills not counted).`}
      />
      {quadrakills.length === 0 ? (
        <p className="text-sm text-text-secondary">No quadra kills {PERIOD_LABEL[since]} yet.</p>
      ) : (
        <ol className="flex flex-col gap-1" aria-label="Quadra kills by player">
          {quadrakills.map((row) => (
            <li key={row.puuid}>
              <Link
                to="/summoner/$region/$riotId"
                params={summonerParams(row.game_name, row.tag_line)}
                aria-label={`${row.game_name}#${row.tag_line}: ${plural(row.count, "quadra kill")}`}
                className={cn(
                  "group/quadra -mx-2 flex min-w-0 items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-surface-2",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
                )}
              >
                <ProfileIcon iconId={players.get(row.puuid)?.iconId} size="xs" alt="" />
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="truncate text-sm font-medium text-text transition-colors group-hover/quadra:text-gold-bright">
                    {playerLabel(players, row)}
                  </span>
                  <span aria-hidden="true" className="block h-1 w-full overflow-hidden rounded-full bg-white/[0.06]">
                    <span
                      className="block h-full rounded-full bg-gold/70"
                      style={{ width: `${max > 0 ? Math.max(4, (row.count / max) * 100) : 0}%` }}
                    />
                  </span>
                </span>
                <span className="w-8 shrink-0 text-right text-sm font-semibold text-text tabular-nums">
                  {formatInteger(row.count)}
                </span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </GlowCard>
  );
}
