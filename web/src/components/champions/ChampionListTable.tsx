import type { MouseEvent } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";

import type { ChampionRole } from "@/api/types";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { championSlug } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatDecimal, formatPercent } from "@/lib/format";
import type { ChampionsSearch } from "@/router";

import {
  CHAMPION_SORT_LABELS,
  championListColumns,
  type ChampionListColumn,
  type ChampionListItem,
  type ChampionListSort,
  type ChampionListSortState,
} from "./ChampionListModel";
import { ChampionGames, ChampionRoleIcons, ChampionTierCell, ChampionWinRate } from "./ChampionListParts";

const ALIGN = { left: "text-left", right: "text-right", center: "text-center" } as const;
const JUSTIFY = { left: "justify-start", right: "justify-end", center: "justify-center" } as const;

/** Sticky header only from lg, where the table fits its card (below that it may scroll sideways). */
const HEADER_CLASS = cn(
  "[&_th]:bg-surface-1 [&_th]:shadow-[inset_0_-1px_0_var(--color-border)]",
  "lg:[&_th]:sticky lg:[&_th]:top-14 lg:[&_th]:z-10 lg:[&_th]:bg-surface-1/92 lg:[&_th]:backdrop-blur-md",
);

export interface ChampionListTableProps {
  items: readonly ChampionListItem[];
  role: ChampionRole | null;
  sort: ChampionListSortState;
  onSort: (key: ChampionListSort) => void;
  /** Patch / queue / role carried over to the champion page. */
  linkSearch: ChampionsSearch;
  className?: string;
}

function isInteractiveTarget(event: MouseEvent): boolean {
  const target = event.target as HTMLElement | null;
  return Boolean(target?.closest("a, button, [role='button']"));
}

/** Desktop champion list: sortable columns; click a row to open the champion. */
export function ChampionListTable({ items, role, sort, onSort, linkSearch, className }: ChampionListTableProps) {
  const navigate = useNavigate();
  const columns = championListColumns(role);
  const sortedBy = `${CHAMPION_SORT_LABELS[sort.key]}, ${sort.direction === "asc" ? "ascending" : "descending"}`;

  const openChampion = (event: MouseEvent, item: ChampionListItem) => {
    if (isInteractiveTarget(event)) return;
    if (window.getSelection()?.toString()) return;
    void navigate({
      to: "/champions/$champion",
      params: { champion: championSlug(item.row.champion_name) },
      search: linkSearch,
    });
  };

  return (
    <Table containerClassName={cn("lg:overflow-visible", className)} className="min-w-[720px] lg:min-w-0 lg:table-fixed">
      <caption className="sr-only">Champions sorted by {sortedBy}.</caption>
      <TableHeader className={HEADER_CLASS}>
        <TableRow>
          {columns.map((column) => (
            <TableHead
              key={column.id}
              scope="col"
              className={cn("h-11 px-2", ALIGN[column.align ?? "left"], column.className)}
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
        {items.map((item, index) => (
          <TableRow
            key={item.row.champion_id}
            onClick={(event) => openChampion(event, item)}
            className={cn(
              "group/row cursor-pointer",
              // Sorted by tier: a slightly stronger rule under the last row of each tier.
              sort.key === "tier" && index < items.length - 1 && items[index + 1]?.tier !== item.tier && "border-b-border-strong",
            )}
          >
            <TableCell className="px-2 pl-4 text-center text-xs font-semibold text-text-muted tabular-nums">
              {item.rank}
            </TableCell>
            <TableCell className={cn("px-2", item.smallSample && "opacity-60")}>
              <Link
                to="/champions/$champion"
                params={{ champion: championSlug(item.row.champion_name) }}
                search={linkSearch}
                className="flex min-w-0 items-center gap-2.5 rounded-lg font-semibold text-text transition-colors hover:text-gold-bright focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold"
              >
                <ChampionIcon champion={item.row.champion_name} size="sm" />
                <span className="truncate">{item.name}</span>
              </Link>
            </TableCell>
            <TableCell className={cn("px-2 text-center", item.smallSample && "opacity-60")}>
              <ChampionTierCell tier={item.tier} role={item.tierRole} showRole={!role} />
            </TableCell>
            <TableCell className={cn("px-2", item.smallSample && "opacity-60")}>
              <ChampionRoleIcons roles={item.mainRoles} active={role} />
            </TableCell>
            <TableCell className={cn("px-2", item.smallSample && "opacity-60")}>
              <ChampionWinRate rate={item.winRate} />
            </TableCell>
            <TableCell className={cn("px-2 text-right text-text-secondary", item.smallSample && "opacity-60")}>
              {formatPercent(item.pickRate, 1)}
            </TableCell>
            <TableCell className={cn("px-2 text-right text-text-secondary", item.smallSample && "opacity-60")}>
              {formatPercent(item.banRate, 1)}
            </TableCell>
            <TableCell className="px-2 text-right font-medium text-text">
              <ChampionGames games={item.games} smallSample={item.smallSample} className={item.smallSample ? "text-text-secondary" : undefined} />
            </TableCell>
            <TableCell
              className={cn(
                "px-2 pr-4 text-right font-medium",
                item.kda >= 3 ? "text-gold-bright" : "text-text",
                item.smallSample && "opacity-60",
              )}
            >
              {formatDecimal(item.kda, 2)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function HeaderContent({
  column,
  sort,
  onSort,
}: {
  column: ChampionListColumn;
  sort: ChampionListSortState;
  onSort: (key: ChampionListSort) => void;
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
  column: ChampionListColumn,
  sortKey: ChampionListSort,
  sort: ChampionListSortState,
  onSort: (key: ChampionListSort) => void,
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
      aria-label={`Sort by ${CHAMPION_SORT_LABELS[sortKey]}`}
    >
      <span>{column.label}</span>
      <Icon className={cn("size-3.5", active ? "text-gold" : "opacity-60")} aria-hidden="true" />
    </button>
  );
}
