import type { MouseEvent } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";

import type { LeaderboardEntry, LeaderboardQueue } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { RolePercentileAverage } from "@/components/common/RolePercentile";
import { FormDots } from "@/components/common/FormDots";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { StreakBadge } from "@/components/common/StreakBadge";
import { WinRateBar } from "@/components/common/WinRateBar";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { LEADERBOARD_FORM_LIMIT } from "@/lib/streaks";
import { formatAvgKdaLine, formatInteger, formatKdaRatio, plural } from "@/lib/format";
import { summonerParams } from "@/lib/riotId";

import { BestAllyLink, LpDelta, RankCell, StandingBadge, TopChampions } from "./parts";
import { LEADERBOARD_COLUMNS, type LeaderboardColumn } from "./columns";
import { displayedRank, SORT_LABELS, type SortKey, type SortState, type Standings } from "./sorting";

/**
 * Below xl the table scrolls sideways inside its card; # and Player stay pinned on the left.
 * Cells carry their own background so pinned cells hide what scrolls beneath them, and the
 * row hover is painted per cell (surface-2) so pinned and scrolling cells match.
 */
const PINNED: Readonly<Record<string, string>> = {
  standing: "max-xl:sticky max-xl:left-0 max-xl:z-[1]",
  player: "max-xl:sticky max-xl:left-[52px] max-xl:z-[1] max-xl:shadow-[inset_-1px_0_0_var(--color-border)]",
};
const CELL = "bg-surface-1 px-2 transition-colors group-hover/row:bg-surface-2";

const ALIGN = { left: "text-left", right: "text-right", center: "text-center" } as const;
const JUSTIFY = { left: "justify-start", right: "justify-end", center: "justify-center" } as const;

/**
 * Sticky header only from xl, where the table fits its card: below that the container
 * scrolls horizontally, which would make it the sticky scroll parent.
 */
const HEADER_CLASS = cn(
  "[&_th]:bg-surface-1 [&_th]:shadow-[inset_0_-1px_0_var(--color-border)]",
  "xl:[&_th]:sticky xl:[&_th]:top-14 xl:[&_th]:z-10 xl:[&_th]:bg-surface-1/92 xl:[&_th]:backdrop-blur-md",
);

export interface LeaderboardTableProps {
  entries: readonly LeaderboardEntry[];
  standings: Standings;
  queue: LeaderboardQueue;
  sort: SortState;
  onSort: (key: SortKey) => void;
  className?: string;
}

function isInteractiveTarget(event: MouseEvent): boolean {
  const target = event.target as HTMLElement | null;
  return Boolean(target?.closest("a, button, [role='button']"));
}

/** Desktop leaderboard: sortable columns, row hover, click anywhere on a row to open the player. */
export function LeaderboardTable({ entries, standings, queue, sort, onSort, className }: LeaderboardTableProps) {
  const navigate = useNavigate();
  const sortedBy = `${SORT_LABELS[sort.key]}, ${sort.direction === "asc" ? "ascending" : "descending"}`;

  const openPlayer = (event: MouseEvent, entry: LeaderboardEntry) => {
    if (isInteractiveTarget(event)) return;
    if (window.getSelection()?.toString()) return;
    void navigate({ to: "/summoner/$region/$riotId", params: summonerParams(entry.game_name, entry.tag_line) });
  };

  return (
    <Table
      containerClassName={cn("xl:overflow-visible", className)}
      className="min-w-[1120px] xl:min-w-0 xl:table-fixed"
    >
      <caption className="sr-only">Season leaderboard of the tracked roster, sorted by {sortedBy}.</caption>
      <TableHeader className={HEADER_CLASS}>
        <TableRow>
          {LEADERBOARD_COLUMNS.map((column) => (
            <TableHead
              key={column.id}
              scope="col"
              className={cn(
                "h-11 px-2",
                ALIGN[column.align ?? "left"],
                column.className,
                PINNED[column.id],
                PINNED[column.id] && "max-xl:z-[2]",
              )}
              aria-sort={
                column.sortKey && sort.key === column.sortKey
                  ? sort.direction === "asc"
                    ? "ascending"
                    : "descending"
                  : undefined
              }
            >
              <HeaderContent column={column} sort={sort} onSort={onSort} />
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map((entry) => {
          const standing = standings.rank.get(entry.puuid) ?? null;
          const needed = standings.gamesNeeded(entry);
          const rank = displayedRank(entry, queue);
          const hasGames = entry.games > 0;
          return (
            <TableRow
              key={entry.puuid}
              onClick={(event) => openPlayer(event, entry)}
              className="group/row cursor-pointer hover:bg-transparent"
            >
              <TableCell className={cn(CELL, "pl-4 text-center", PINNED.standing)}>
                {needed > 0 ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="inline-flex">
                        <StandingBadge standing={null} />
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>
                      No standing yet: needs {plural(needed, "more ranked game")} this season.
                    </TooltipContent>
                  </Tooltip>
                ) : (
                  <StandingBadge standing={standing} />
                )}
              </TableCell>
              <TableCell className={cn(CELL, PINNED.player)}>
                <Link
                  to="/summoner/$region/$riotId"
                  params={summonerParams(entry.game_name, entry.tag_line)}
                  className="flex max-w-60 min-w-0 items-center gap-2.5 rounded-lg"
                >
                  <ProfileIcon iconId={entry.profile_icon_id} size="sm" alt="" />
                  {/* The tag sits under the name: together they truncate common 15-character names. */}
                  <span className="flex min-w-0 flex-col leading-tight">
                    <span className="truncate font-semibold text-text transition-colors group-hover/row:text-gold-bright">
                      {entry.game_name}
                    </span>
                    <span className="truncate text-xs text-text-muted tabular-nums">
                      #{entry.tag_line}
                      {entry.summoner_level !== null ? ` · Level ${entry.summoner_level}` : ""}
                    </span>
                  </span>
                </Link>
              </TableCell>
              <TableCell className={CELL}>
                <RankCell rank={rank} />
              </TableCell>
              <TableCell className={cn(CELL, "text-right font-semibold text-text")}>
                {formatInteger(entry.games)}
              </TableCell>
              <TableCell className={CELL}>
                {hasGames ? (
                  <WinRateBar wins={entry.wins} losses={entry.losses} size="sm" className="w-full max-w-28" />
                ) : (
                  <span className="text-xs text-text-muted">No games</span>
                )}
              </TableCell>
              <TableCell className={CELL}>
                {hasGames ? (
                  <span className="flex flex-col leading-tight">
                    <span className={cn("font-semibold", entry.kda >= 4 ? "text-gold-bright" : "text-text")}>
                      {formatKdaRatio(entry.kda, entry.avg_deaths === 0 ? 0 : undefined)}
                      <span className="ml-1 text-xs font-normal text-text-muted">KDA</span>
                    </span>
                    <span className="text-xs text-text-muted">
                      {formatAvgKdaLine(entry.avg_kills, entry.avg_deaths, entry.avg_assists)}
                    </span>
                  </span>
                ) : (
                  <span className="text-xs text-text-muted">–</span>
                )}
              </TableCell>
              <TableCell className={cn(CELL, "text-center")}>
                <span className="inline-flex flex-col items-center gap-0.5">
                  <AiScoreBadge
                    score={entry.avg_ai_score}
                    kind="average"
                    detail={hasGames ? `Over ${plural(entry.games, "ranked game")} this season.` : undefined}
                  />
                  {needed > 0 ? null : (
                    <RolePercentileAverage
                      percentile={entry.avg_ai_role_percentile}
                      games={entry.games}
                      minGames={standings.minGames}
                      size="xs"
                    />
                  )}
                </span>
              </TableCell>
              <TableCell className={cn(CELL, "text-right")}>
                <LpDelta value={entry.lp_delta} />
              </TableCell>
              <TableCell className={CELL}>
                <BestAllyLink ally={entry.best_ally} showIcon={false} className="max-w-full" />
              </TableCell>
              <TableCell className={CELL}>
                <TopChampions champions={entry.top_champions} />
              </TableCell>
              <TableCell className={cn(CELL, "pr-4")}>
                <span className="flex items-center gap-1.5 whitespace-nowrap">
                  <FormDots results={entry.recent_form} limit={10} size="sm" className="flex-nowrap" />
                  <StreakBadge results={entry.recent_form} limit={LEADERBOARD_FORM_LIMIT} size="sm" />
                </span>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function HeaderContent({
  column,
  sort,
  onSort,
}: {
  column: LeaderboardColumn;
  sort: SortState;
  onSort: (key: SortKey) => void;
}) {
  const align = column.align ?? "left";
  const label = column.sortKey ? (
    sortButton(column, column.sortKey, sort, onSort, align)
  ) : (
    <span className={cn(column.hint && "cursor-help underline decoration-dotted underline-offset-4")}>
      {column.label}
    </span>
  );
  if (!column.hint) return label;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{label}</TooltipTrigger>
      <TooltipContent className="tracking-normal normal-case">{column.hint}</TooltipContent>
    </Tooltip>
  );
}

/** A plain element (not a component) so Tooltip's asChild can attach its handlers to it. */
function sortButton(
  column: LeaderboardColumn,
  sortKey: SortKey,
  sort: SortState,
  onSort: (key: SortKey) => void,
  align: "left" | "right" | "center",
) {
  const active = sort.key === sortKey;
  const Icon = !active ? ChevronsUpDown : sort.direction === "asc" ? ArrowUp : ArrowDown;
  return (
    <button
      type="button"
      onClick={() => onSort(sortKey)}
      className={cn(
        "-mx-1.5 inline-flex h-7 items-center gap-1 rounded-md px-1.5 font-semibold tracking-[0.08em] uppercase transition-colors hover:bg-white/5 hover:text-text",
        active ? "text-gold-bright" : "text-text-muted",
        align === "right" && "flex-row-reverse",
        JUSTIFY[align],
      )}
      aria-label={`Sort by ${SORT_LABELS[sortKey]}`}
    >
      <span>{column.label}</span>
      <Icon className={cn("size-3.5", active ? "text-gold" : "opacity-60")} aria-hidden="true" />
    </button>
  );
}
