/**
 * One record category: the holder big (champion, player icon, value, date), then #2 and #3
 * small. Every entry links to its match with the record holder highlighted.
 */
import { Link } from "@tanstack/react-router";
import { Sparkles } from "lucide-react";

import type { RecordCategory, RecordEntry, RecordScope } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { GlowCard } from "@/components/common/GlowCard";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { playerSearchValue } from "@/components/match/focus";
import { championDisplayName } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import { toScore100 } from "@/lib/score";

import {
  formatCompactDate,
  formatRecordValue,
  playerLabel,
  RECORD_META,
  recordValueText,
  resultLabel,
  type PlayerLookup,
} from "./recordMeta";

const ENTRY_LINK =
  "rounded-xl transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold";

function entryKey(entry: RecordEntry): string {
  return `${entry.match_id}:${entry.puuid}`;
}

function entryLabel(category: RecordCategory, entry: RecordEntry): string {
  const champion = championDisplayName(entry.champion_name);
  return `${category.label}, #${entry.rank}: ${recordValueText(category, entry.value)} by ${entry.game_name}#${entry.tag_line} as ${champion}, ${formatDate(entry.game_start)}, ${resultLabel(entry)}. Open match.`;
}

function ResultMark({ win }: { win: boolean }) {
  return (
    <span className={cn("font-semibold", win ? "text-win" : "text-loss")} aria-hidden="true">
      {win ? "W" : "L"}
    </span>
  );
}

/** The record holder: champion with the player's icon, the value big, who and when. */
function TopEntry({
  category,
  entry,
  scope,
  players,
}: {
  category: RecordCategory;
  entry: RecordEntry;
  scope: RecordScope;
  players: PlayerLookup;
}) {
  const meta = RECORD_META[category.key];
  const champion = championDisplayName(entry.champion_name);
  // One player's records all belong to them, so the champion leads instead of their name.
  const who = scope === "player" ? champion : playerLabel(players, entry);
  const detail = scope === "player" ? formatDate(entry.game_start) : `${champion} · ${formatDate(entry.game_start)}`;
  return (
    <Link
      to="/match/$matchId"
      params={{ matchId: entry.match_id }}
      search={{ player: playerSearchValue(entry) }}
      aria-label={entryLabel(category, entry)}
      className={cn("group/top -mx-2 flex min-w-0 items-center gap-3 px-2 py-1.5", ENTRY_LINK)}
    >
      <span className="relative shrink-0">
        <ChampionIcon champion={entry.champion_name} size="lg" />
        {scope === "roster" ? (
          <ProfileIcon
            iconId={players.get(entry.puuid)?.iconId}
            size="xs"
            alt=""
            className="absolute -right-1.5 -bottom-1.5"
          />
        ) : null}
      </span>
      <span className="flex min-w-0 flex-col gap-1">
        {category.unit === "score" ? (
          <AiScoreBadge score={entry.value} size="lg" tooltip={false} className="w-fit" />
        ) : (
          <span className="flex items-baseline gap-1.5">
            <span className="font-display text-[28px] leading-none font-bold text-text tabular-nums">
              {formatRecordValue(category.unit, entry.value)}
            </span>
            {meta.suffix ? <span className="text-xs font-medium text-text-secondary">{meta.suffix}</span> : null}
          </span>
        )}
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-sm font-semibold text-text transition-colors group-hover/top:text-gold-bright">
            {who}
          </span>
          <span className="truncate text-xs text-text-secondary tabular-nums">
            {detail} · <ResultMark win={entry.win} />
          </span>
        </span>
      </span>
    </Link>
  );
}

/** #2 and #3: rank, champion, who, value on one line. */
function RunnerUp({
  category,
  entry,
  scope,
  players,
}: {
  category: RecordCategory;
  entry: RecordEntry;
  scope: RecordScope;
  players: PlayerLookup;
}) {
  const champion = championDisplayName(entry.champion_name);
  const who = scope === "player" ? `${champion} · ${formatCompactDate(entry.game_start)}` : playerLabel(players, entry);
  return (
    <Link
      to="/match/$matchId"
      params={{ matchId: entry.match_id }}
      search={{ player: playerSearchValue(entry) }}
      aria-label={entryLabel(category, entry)}
      title={`${entry.game_name}#${entry.tag_line} · ${champion} · ${formatDate(entry.game_start)} · ${resultLabel(entry)}`}
      className={cn("-mx-2 flex h-8 min-w-0 items-center gap-2 rounded-lg px-2 text-xs", ENTRY_LINK)}
    >
      <span className="w-3 shrink-0 text-center text-[11px] font-semibold text-text-muted tabular-nums">
        {entry.rank}
      </span>
      <ChampionIcon champion={entry.champion_name} size="xs" />
      <span className="min-w-0 flex-1 truncate text-text-secondary">{who}</span>
      {category.unit === "score" ? (
        <AiScoreBadge score={entry.value} size="sm" tooltip={false} />
      ) : (
        <span className="shrink-0 font-semibold text-text tabular-nums">
          {formatRecordValue(category.unit, entry.value)}
        </span>
      )}
    </Link>
  );
}

export interface RecordCardProps {
  category: RecordCategory;
  scope: RecordScope;
  players: PlayerLookup;
  className?: string;
}

/** A record category card for the /records grid. */
export function RecordCard({ category, scope, players, className }: RecordCardProps) {
  const meta = RECORD_META[category.key];
  const Icon = meta.icon;
  const [top, ...rest] = category.entries;
  return (
    <GlowCard className={cn("flex h-full flex-col gap-3 p-4", className)}>
      <div className="flex items-center gap-2">
        <Icon className="size-4 shrink-0 text-gold" aria-hidden="true" />
        <h3 className="truncate text-sm font-semibold text-text">{category.label}</h3>
      </div>
      {top ? (
        <TopEntry category={category} entry={top} scope={scope} players={players} />
      ) : (
        <p className="flex min-h-[68px] items-center text-sm text-text-muted">No qualifying game yet.</p>
      )}
      {rest.length > 0 ? (
        <ol className="flex flex-col gap-0.5 border-t border-border pt-2" aria-label={`${category.label}, runners-up`}>
          {rest.map((entry) => (
            <li key={entryKey(entry)}>
              <RunnerUp category={category} entry={entry} scope={scope} players={players} />
            </li>
          ))}
        </ol>
      ) : null}
      {meta.note ? <p className="mt-auto pt-1 text-[11px] leading-4 text-text-muted">{meta.note}</p> : null}
    </GlowCard>
  );
}

/**
 * Highest AI Score, as a wide card after the grid (cyan: an AI feature). The best stat lines
 * sit a hair below 100, so the card says why every entry reads 100.
 */
export function AiScoreRecordCard({
  category,
  scope,
  players,
  modelVersion,
  className,
}: RecordCardProps & { modelVersion: string | null }) {
  const roundsToMax = category.entries.filter((entry) => toScore100(entry.value) === 100).length;
  return (
    <GlowCard glow="cyan" className={cn("flex h-full flex-col gap-3 p-4 sm:p-5", className)}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Sparkles className="size-4 shrink-0 text-cyan" aria-hidden="true" />
        <h3 className="text-sm font-semibold text-text">{category.label}</h3>
        <span className="text-xs text-text-secondary">Stat lines that look the most like a win</span>
      </div>
      {category.entries.length === 0 ? (
        <p className="text-sm text-text-muted">
          {modelVersion ? "No scored game yet." : "Not scored: AI Scores appear once a model is trained."}
        </p>
      ) : (
        <ol className="grid gap-2 xl:grid-cols-3" aria-label={category.label}>
          {category.entries.map((entry) => {
            const champion = championDisplayName(entry.champion_name);
            return (
              <li key={entryKey(entry)} className="min-w-0">
                <Link
                  to="/match/$matchId"
                  params={{ matchId: entry.match_id }}
                  search={{ player: playerSearchValue(entry) }}
                  aria-label={entryLabel(category, entry)}
                  className={cn(
                    "flex min-w-0 items-center gap-3 border border-border bg-surface-2/50 p-2.5",
                    ENTRY_LINK,
                  )}
                >
                  <span className="w-3 shrink-0 text-center text-[11px] font-semibold text-text-muted tabular-nums">
                    {entry.rank}
                  </span>
                  <span className="relative shrink-0">
                    <ChampionIcon champion={entry.champion_name} size="md" />
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
                    <span className="truncate text-sm font-semibold text-text">
                      {scope === "player" ? champion : playerLabel(players, entry)}
                    </span>
                    <span className="truncate text-xs text-text-secondary tabular-nums">
                      {scope === "player" ? "" : `${champion} · `}
                      {formatCompactDate(entry.game_start)} · <ResultMark win={entry.win} />
                    </span>
                  </span>
                  <AiScoreBadge score={entry.value} tooltip={false} />
                </Link>
              </li>
            );
          })}
        </ol>
      )}
      {roundsToMax > 1 ? (
        <p className="text-[11px] leading-4 text-text-muted">
          One-sided wins produce stat lines the model scores within a hair of 100, so these all round to 100; the order
          uses the unrounded scores.
        </p>
      ) : null}
    </GlowCard>
  );
}
