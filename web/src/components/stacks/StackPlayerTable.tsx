import { useMemo, useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ArrowDown, ArrowUp, ChevronsUpDown, Users } from "lucide-react";

import type { StackPlayer, StackSummary } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { GlowCard } from "@/components/common/GlowCard";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { SectionHeader } from "@/components/common/SectionHeader";
import { WinRateBar } from "@/components/common/WinRateBar";
import { KdaRatio } from "@/components/match/MatchBits";
import { CARRY_GAP, EDGE_GAP, HARD_GAP } from "@/components/match/verdicts";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { championDisplayName } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatAvgKdaLine, formatInteger, plural } from "@/lib/format";
import { summonerParams } from "@/lib/riotId";
import { AI_AVERAGE_NOTE } from "@/lib/score";

// --- sorting ------------------------------------------------------------------------------

type SortKey = "player" | "games" | "winrate" | "ai" | "kda" | "carries" | "ran_downs" | "tried";
type SortDirection = "asc" | "desc";
interface SortState {
  key: SortKey;
  direction: SortDirection;
}

/** Most games first: the API's own order (ties keep it too). */
const DEFAULT_SORT: SortState = { key: "games", direction: "desc" };

const SORT_LABELS: Readonly<Record<SortKey, string>> = {
  player: "Name",
  games: "Games",
  winrate: "Win rate",
  ai: "Average AI Score",
  kda: "KDA",
  carries: "Carries",
  ran_downs: "Ran it down",
  tried: "Tried their best",
};

const collator = new Intl.Collator("en", { sensitivity: "base", numeric: true });

function sortValue(player: StackPlayer, key: Exclude<SortKey, "player">): number | null {
  switch (key) {
    case "games":
      return player.games;
    case "winrate":
      return player.games > 0 ? player.winrate : null;
    case "ai":
      return player.avg_ai_score;
    case "kda":
      return player.games > 0 ? player.kda : null;
    case "carries":
      return player.carries;
    case "ran_downs":
      return player.ran_downs;
    case "tried":
      return player.tried;
  }
}

/** Missing values sink whichever way a column is sorted; ties keep the API order. */
function sortPlayers(players: readonly StackPlayer[], sort: SortState): StackPlayer[] {
  const sign = sort.direction === "asc" ? 1 : -1;
  const indexed = players.map((player, index) => ({ player, index }));
  indexed.sort((a, b) => {
    if (sort.key === "player") {
      return sign * collator.compare(a.player.game_name, b.player.game_name) || a.index - b.index;
    }
    const va = sortValue(a.player, sort.key);
    const vb = sortValue(b.player, sort.key);
    if (va === null && vb === null) return a.index - b.index;
    if (va === null) return 1;
    if (vb === null) return -1;
    return sign * (va - vb) || a.index - b.index;
  });
  return indexed.map(({ player }) => player);
}

function nextSort(current: SortState, key: SortKey): SortState {
  if (current.key === key) return { key, direction: current.direction === "asc" ? "desc" : "asc" };
  return { key, direction: key === "player" ? "asc" : "desc" };
}

// --- columns ------------------------------------------------------------------------------

const VERDICT_SCOPE = "Counted in stacks where every member was scored by the AI model.";

interface Column {
  id: string;
  label: string;
  sortKey?: SortKey;
  align?: "left" | "right" | "center";
  hint?: string;
  className?: string;
}

const COLUMNS: readonly Column[] = [
  { id: "player", label: "Player", sortKey: "player", className: "pl-0" },
  { id: "games", label: "Games", sortKey: "games", align: "right", className: "w-16" },
  { id: "winrate", label: "Win rate", sortKey: "winrate", className: "w-28" },
  {
    id: "ai",
    label: "AI Score",
    sortKey: "ai",
    align: "center",
    className: "w-[88px]",
    hint: `Average AI Score in these stacks (0 to 100). ${AI_AVERAGE_NOTE}`,
  },
  { id: "kda", label: "KDA", sortKey: "kda", className: "w-[120px]", hint: "KDA ratio, then average kills / deaths / assists per game" },
  {
    id: "carries",
    label: "Carries",
    sortKey: "carries",
    align: "center",
    className: "w-[72px]",
    hint: `Wins where their AI Score beat every teammate's by ${EDGE_GAP} or more (${HARD_GAP}+ is a hard carry). ${VERDICT_SCOPE}`,
  },
  {
    id: "ran_downs",
    label: "Ran it down",
    sortKey: "ran_downs",
    align: "center",
    className: "w-[108px]",
    hint: `Losses where their AI Score trailed every teammate's by ${CARRY_GAP} or more. ${VERDICT_SCOPE}`,
  },
  {
    id: "tried",
    label: "Tried",
    sortKey: "tried",
    align: "center",
    className: "w-16",
    hint: `Losses where they topped the squad by ${CARRY_GAP} or more and nobody ran it down. ${VERDICT_SCOPE}`,
  },
  { id: "champion", label: "Top champ", className: "w-32 pr-0", hint: "Most played champion in these stacks" },
];

const ALIGN = { left: "text-left", right: "text-right", center: "text-center" } as const;
const JUSTIFY = { left: "justify-start", right: "justify-end", center: "justify-center" } as const;

// --- small pieces -------------------------------------------------------------------------

function perGame(total: number, games: number): number {
  return games > 0 ? total / games : 0;
}

function aiDetail(player: StackPlayer): string | undefined {
  if (player.scored_games === 0) return undefined;
  return `Over ${plural(player.scored_games, "scored stack")}.`;
}

type VerdictKind = "carries" | "ran_downs" | "tried";

/** Verdict count: coloured when above zero, with the breakdown in a tooltip and for screen readers. */
function VerdictCount({ player, kind, className }: { player: StackPlayer; kind: VerdictKind; className?: string }) {
  const count = player[kind];
  let text: string;
  let tone: string;
  if (kind === "carries") {
    text =
      count === 0
        ? "No carries"
        : `${plural(count, "carry", "carries")}${player.hard_carries > 0 ? `, ${plural(player.hard_carries, "hard carry", "hard carries")}` : ""}`;
    tone = "text-gold";
  } else if (kind === "ran_downs") {
    text =
      count === 0
        ? "Never ran it down"
        : `Ran it down ${plural(count, "time")}${player.off_days > 0 ? `, plus ${plural(player.off_days, "off day")}` : ""}`;
    tone = "text-loss";
  } else {
    text = count === 0 ? "No losses where they tried their best" : `Tried their best in ${plural(count, "loss", "losses")}`;
    tone = "text-gold";
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "inline-flex min-w-6 cursor-default justify-center font-semibold tabular-nums",
            count > 0 ? tone : "text-text-muted",
            className,
          )}
        >
          <span aria-hidden="true">{formatInteger(count)}</span>
          <span className="sr-only">{text}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  );
}

function PlayerLink({ player, className }: { player: StackPlayer; className?: string }) {
  return (
    <Link
      to="/summoner/$region/$riotId"
      params={summonerParams(player.game_name, player.tag_line)}
      className={cn("group/player flex min-w-0 items-center gap-2.5 rounded-lg", className)}
    >
      <ProfileIcon iconId={player.profile_icon_id} size="sm" alt="" />
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="truncate font-semibold text-text transition-colors group-hover/player:text-gold-bright">
          {player.game_name}
        </span>
        <span className="truncate text-xs text-text-muted">#{player.tag_line}</span>
      </span>
    </Link>
  );
}

function KdaCell({ player }: { player: StackPlayer }) {
  if (player.games === 0) return <span className="text-xs text-text-muted">–</span>;
  const g = player.games;
  return (
    <span className="flex min-w-0 flex-col leading-tight">
      <KdaRatio kda={player.kda} deaths={player.deaths} />
      <span className="truncate text-xs font-normal text-text-muted tabular-nums">
        {formatAvgKdaLine(perGame(player.kills, g), perGame(player.deaths, g), perGame(player.assists, g))}
      </span>
    </span>
  );
}

function TopChampion({ player, className }: { player: StackPlayer; className?: string }) {
  if (!player.top_champion_name) return <span className={cn("text-xs text-text-muted", className)}>–</span>;
  const name = championDisplayName(player.top_champion_name);
  return (
    <span className={cn("flex min-w-0 items-center gap-2", className)}>
      <ChampionIcon champion={player.top_champion_name} size="xs" />
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="truncate text-[13px] font-medium text-text">{name}</span>
        <span className="text-xs text-text-muted tabular-nums">{plural(player.top_champion_games, "game")}</span>
      </span>
    </span>
  );
}

function SortHeader({ column, sort, onSort }: { column: Column; sort: SortState; onSort: (key: SortKey) => void }) {
  const align = column.align ?? "left";
  let label: ReactNode;
  if (column.sortKey) {
    const key = column.sortKey;
    const active = sort.key === key;
    const Icon = !active ? ChevronsUpDown : sort.direction === "asc" ? ArrowUp : ArrowDown;
    label = (
      <button
        type="button"
        onClick={() => onSort(key)}
        className={cn(
          "-mx-1.5 inline-flex h-7 items-center gap-1 rounded-md px-1.5 font-semibold tracking-[0.08em] uppercase transition-colors hover:bg-white/5 hover:text-text",
          active ? "text-gold-bright" : "text-text-muted",
          align === "right" && "flex-row-reverse",
          JUSTIFY[align],
        )}
        aria-label={`Sort by ${SORT_LABELS[key]}`}
      >
        <span>{column.label}</span>
        <Icon className={cn("size-3.5", active ? "text-gold" : "opacity-60")} aria-hidden="true" />
      </button>
    );
  } else {
    label = (
      <span className={cn(column.hint && "cursor-help underline decoration-dotted underline-offset-4")}>
        {column.label}
      </span>
    );
  }
  if (!column.hint) return label;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{label}</TooltipTrigger>
      <TooltipContent className="max-w-72 tracking-normal normal-case">{column.hint}</TooltipContent>
    </Tooltip>
  );
}

// --- wide table ---------------------------------------------------------------------------

function PlayerTable({
  players,
  sort,
  onSort,
}: {
  players: readonly StackPlayer[];
  sort: SortState;
  onSort: (key: SortKey) => void;
}) {
  const sortedBy = `${SORT_LABELS[sort.key]}, ${sort.direction === "asc" ? "ascending" : "descending"}`;
  return (
    <Table className="min-w-[920px] table-fixed">
      <caption className="sr-only">Roster players in these stacks, sorted by {sortedBy}.</caption>
      <TableHeader>
        <TableRow>
          {COLUMNS.map((column) => (
            <TableHead
              key={column.id}
              scope="col"
              className={cn("h-10 px-2", ALIGN[column.align ?? "left"], column.className)}
              aria-sort={
                column.sortKey && sort.key === column.sortKey
                  ? sort.direction === "asc"
                    ? "ascending"
                    : "descending"
                  : undefined
              }
            >
              <SortHeader column={column} sort={sort} onSort={onSort} />
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {players.map((player) => (
          <TableRow key={player.puuid}>
            <TableCell className="px-2 pl-0">
              <PlayerLink player={player} className="max-w-full" />
            </TableCell>
            <TableCell className="px-2 text-right font-semibold text-text">{formatInteger(player.games)}</TableCell>
            <TableCell className="px-2">
              <WinRateBar wins={player.wins} losses={player.games - player.wins} size="sm" className="w-full max-w-28" />
            </TableCell>
            <TableCell className="px-2 text-center">
              <AiScoreBadge score={player.avg_ai_score} kind="average" detail={aiDetail(player)} />
            </TableCell>
            <TableCell className="px-2">
              <KdaCell player={player} />
            </TableCell>
            <TableCell className="px-2 text-center">
              <VerdictCount player={player} kind="carries" />
            </TableCell>
            <TableCell className="px-2 text-center">
              <VerdictCount player={player} kind="ran_downs" />
            </TableCell>
            <TableCell className="px-2 text-center">
              <VerdictCount player={player} kind="tried" />
            </TableCell>
            <TableCell className="px-2 pr-0">
              <TopChampion player={player} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

// --- narrow cards -------------------------------------------------------------------------

function Stat({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <dt className="label-caps">{label}</dt>
      <dd className="min-w-0 text-sm font-semibold text-text tabular-nums">{children}</dd>
    </div>
  );
}

function PlayerCard({ player }: { player: StackPlayer }) {
  return (
    <li className="flex min-w-0 flex-col gap-3 rounded-xl border border-border bg-surface-2/50 p-3.5">
      <div className="flex items-center gap-3">
        <PlayerLink player={player} className="flex-1" />
        <AiScoreBadge
          score={player.avg_ai_score}
          kind="average"
          className="shrink-0"
          detail={aiDetail(player)}
        />
      </div>
      <WinRateBar wins={player.wins} losses={player.games - player.wins} size="sm" />
      <dl className="grid grid-cols-[auto_minmax(0,1fr)_minmax(0,1.3fr)] gap-3">
        <Stat label="Games">{formatInteger(player.games)}</Stat>
        <Stat label="KDA">
          <KdaCell player={player} />
        </Stat>
        <Stat label="Top champ">
          <TopChampion player={player} />
        </Stat>
      </dl>
      <dl className="grid grid-cols-3 gap-2 border-t border-border pt-3 text-center">
        <div className="flex flex-col items-center gap-0.5">
          <dt className="label-caps">Carries</dt>
          <dd>
            <VerdictCount player={player} kind="carries" />
          </dd>
        </div>
        <div className="flex flex-col items-center gap-0.5">
          <dt className="label-caps">Ran it down</dt>
          <dd>
            <VerdictCount player={player} kind="ran_downs" />
          </dd>
        </div>
        <div className="flex flex-col items-center gap-0.5">
          <dt className="label-caps">Tried</dt>
          <dd>
            <VerdictCount player={player} kind="tried" />
          </dd>
        </div>
      </dl>
    </li>
  );
}

// --- section ------------------------------------------------------------------------------

/** "Squad in stacks": one row per roster player (a table on wide screens, cards on narrow ones). */
export function StackPlayerTable({ data }: { data: StackSummary }) {
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);
  const players = useMemo(() => sortPlayers(data.players, sort), [data.players, sort]);

  if (data.players.length === 0) return null;

  return (
    <GlowCard className="flex flex-col gap-4 p-4 sm:p-5">
      <SectionHeader eyebrow="Players" title="Squad in stacks" icon={Users} />

      <div className="hidden lg:block">
        <PlayerTable players={players} sort={sort} onSort={(key) => setSort(nextSort(sort, key))} />
      </div>
      <ul className="grid gap-3 sm:grid-cols-2 lg:hidden" aria-label="Roster players in these stacks">
        {players.map((player) => (
          <PlayerCard key={player.puuid} player={player} />
        ))}
      </ul>

      <p className="text-xs leading-relaxed text-text-muted">
        {AI_AVERAGE_NOTE} Carries, ran it down and tried compare teammates' AI Scores in the same game, only in stacks
        where everyone was scored.
      </p>
    </GlowCard>
  );
}
