/**
 * Overview tab: the player's personal bests this season (player-scope records, best game per
 * category) in a compact grid, with "See all" to /records?player=<puuid>. Hidden until the
 * player has a handful of ranked games, where "best" starts to mean something.
 */
import { Link } from "@tanstack/react-router";
import { ArrowRight, Crown, Medal } from "lucide-react";

import { useRecords } from "@/api/queries";
import type { RecordCategory, RecordEntry, Records } from "@/api/types";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { ErrorState } from "@/components/common/ErrorState";
import { GlowCard } from "@/components/common/GlowCard";
import { SectionHeader } from "@/components/common/SectionHeader";
import { playerSearchValue } from "@/components/match/focus";
import {
  categoriesByKey,
  formatCompactDate,
  formatRecordValue,
  PERSONAL_BEST_KEYS,
  RECORD_META,
  recordValueText,
  resultLabel,
} from "@/components/records/recordMeta";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { championDisplayName } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatDate, plural } from "@/lib/format";

/** Fewer ranked games than this this season: the card stays hidden. */
const MIN_GAMES = 5;

/**
 * Enough entries to tell whether the player has MIN_GAMES games: longest_game lists every
 * match once, so its length is min(limit, games).
 */
const LIMIT = MIN_GAMES;

export interface PersonalBestsCardProps {
  puuid: string;
}

function hasEnoughGames(data: Records): boolean {
  const games = data.categories.find((category) => category.key === "longest_game")?.entries.length ?? 0;
  return games >= MIN_GAMES;
}

function BestTile({ category, entry }: { category: RecordCategory; entry: RecordEntry }) {
  const meta = RECORD_META[category.key];
  const Icon = meta.icon;
  const champion = championDisplayName(entry.champion_name);
  return (
    <Link
      to="/match/$matchId"
      params={{ matchId: entry.match_id }}
      search={{ player: playerSearchValue(entry) }}
      aria-label={`Best ${meta.short.toLowerCase()}: ${recordValueText(category, entry.value)} as ${champion}, ${formatDate(entry.game_start)}, ${resultLabel(entry)}. Open match.`}
      className={cn(
        "group/best flex min-w-0 flex-col gap-2 rounded-xl border border-border bg-surface-2/50 p-3",
        "transition-[border-color,background-color] duration-150 hover:border-border-strong hover:bg-surface-2",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
      )}
    >
      <span className="flex items-center gap-1.5">
        <Icon className="size-3.5 shrink-0 text-gold" aria-hidden="true" />
        <span className="label-caps truncate">{meta.short}</span>
      </span>
      <span className="font-display text-2xl leading-none font-bold text-text tabular-nums">
        {formatRecordValue(category.unit, entry.value)}
      </span>
      <span className="flex min-w-0 items-center gap-1.5">
        <ChampionIcon champion={entry.champion_name} size="xs" />
        <span className="truncate text-xs text-text-secondary tabular-nums">
          {formatCompactDate(entry.game_start)}
          <span aria-hidden="true"> · </span>
          <span className={entry.win ? "text-win" : "text-loss"}>{entry.win ? "W" : "L"}</span>
        </span>
      </span>
    </Link>
  );
}

function TileSkeleton() {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border p-3" aria-hidden="true">
      <Skeleton className="h-3 w-20" />
      <Skeleton className="h-6 w-14" />
      <div className="flex items-center gap-1.5">
        <Skeleton className="size-5 rounded-md" />
        <Skeleton className="h-3 w-16" />
      </div>
    </div>
  );
}

export function PersonalBestsCard({ puuid }: PersonalBestsCardProps) {
  const query = useRecords({ puuid, limit: LIMIT });
  const data = query.data?.puuid === puuid ? query.data : undefined;

  // Too few games for "best" to mean much: stay out of the way (the season card says it once).
  if (data && !hasEnoughGames(data)) return null;

  const byKey = data ? categoriesByKey(data.categories) : null;
  const tiles = byKey
    ? PERSONAL_BEST_KEYS.flatMap((key) => {
        const category = byKey.get(key);
        const best = category?.entries[0];
        return category && best ? [{ category, entry: best }] : [];
      })
    : [];
  const pentakills = data ? data.pentakills.reduce((sum, entry) => sum + Math.round(entry.value), 0) : 0;

  return (
    <GlowCard className="flex flex-col gap-4 p-4 sm:p-5">
      <SectionHeader
        title="Personal bests"
        eyebrow="This season"
        icon={Medal}
        action={
          <>
            {pentakills > 0 ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-gold/40 bg-gold/12 px-2 py-0.5 text-[11px] leading-4 font-bold text-gold-bright tabular-nums">
                <Crown className="size-3" aria-hidden="true" />
                {plural(pentakills, "pentakill")}
              </span>
            ) : null}
            <Button variant="ghost" size="sm" asChild className="text-gold hover:text-gold-bright">
              <Link to="/records" search={{ player: puuid }}>
                See all
                <ArrowRight aria-hidden="true" />
              </Link>
            </Button>
          </>
        }
      />
      {query.isError && !data ? (
        <ErrorState compact error={query.error} title="Couldn't load personal bests" onRetry={() => void query.refetch()} />
      ) : (
        <ul
          className="grid grid-cols-2 gap-2 sm:grid-cols-4"
          aria-label="Personal bests"
          aria-busy={!data || undefined}
        >
          {data
            ? tiles.map(({ category, entry }) => (
                <li key={category.key} className="min-w-0">
                  <BestTile category={category} entry={entry} />
                </li>
              ))
            : PERSONAL_BEST_KEYS.map((key) => (
                <li key={key}>
                  <TileSkeleton />
                </li>
              ))}
        </ul>
      )}
    </GlowCard>
  );
}
