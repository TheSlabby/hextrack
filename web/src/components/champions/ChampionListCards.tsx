import { Link } from "@tanstack/react-router";
import { ArrowDownWideNarrow, ArrowUpNarrowWide } from "lucide-react";

import type { ChampionRole } from "@/api/types";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { GlowCard } from "@/components/common/GlowCard";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { championSlug } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatDecimal, formatInteger, formatPercent } from "@/lib/format";
import type { ChampionsSearch } from "@/router";

import {
  CHAMPION_SORT_LABELS,
  CHAMPION_SORT_MENU,
  defaultChampionDirection,
  type ChampionListItem,
  type ChampionListSort,
  type ChampionListSortState,
} from "./ChampionListModel";
import { ChampionRoleIcons, ChampionWinRate } from "./ChampionListParts";

export interface ChampionListCardsProps {
  items: readonly ChampionListItem[];
  role: ChampionRole | null;
  linkSearch: ChampionsSearch;
  className?: string;
}

/** Phone champion list: one compact linked row per champion, the same data as the table. */
export function ChampionListCards({ items, role, linkSearch, className }: ChampionListCardsProps) {
  return (
    <GlowCard className={cn("overflow-clip", className)}>
      <ul className="divide-y divide-border" aria-label="Champions">
        {items.map((item) => (
          <li key={item.row.champion_id}>
            <Link
              to="/champions/$champion"
              params={{ champion: championSlug(item.row.champion_name) }}
              search={linkSearch}
              className="flex min-w-0 items-center gap-2.5 px-3 py-2.5 transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-gold"
            >
              <span className="w-6 shrink-0 text-center text-xs font-semibold text-text-muted tabular-nums">
                {item.rank}
              </span>
              <span className={cn("flex min-w-0 flex-1 items-center gap-2.5", item.smallSample && "opacity-60")}>
                <ChampionIcon champion={item.row.champion_name} size="sm" />
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="truncate text-sm font-semibold text-text">{item.name}</span>
                    <ChampionRoleIcons roles={item.mainRoles} active={role} className="shrink-0 [&_svg]:size-3.5" />
                  </span>
                  <span className="flex flex-wrap gap-x-2 text-[11px] text-text-muted tabular-nums">
                    <span>Pick {formatPercent(item.pickRate, 1)}</span>
                    <span>Ban {formatPercent(item.banRate, 1)}</span>
                    <span>
                      {formatInteger(item.games)} games{item.smallSample ? " · small sample" : ""}
                    </span>
                  </span>
                </span>
                <span className="flex shrink-0 flex-col items-end gap-0.5">
                  <ChampionWinRate rate={item.winRate} className="items-end" />
                  <span className="text-[11px] text-text-muted tabular-nums">KDA {formatDecimal(item.kda, 2)}</span>
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </GlowCard>
  );
}

/** Phone sort controls: a "Sort by" menu plus a direction toggle. */
export function ChampionListSortMenu({
  sort,
  onChange,
  className,
}: {
  sort: ChampionListSortState;
  onChange: (sort: ChampionListSortState) => void;
  className?: string;
}) {
  const ascending = sort.direction === "asc";
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="label-caps shrink-0">Sort by</span>
      <Select
        value={sort.key}
        onValueChange={(key) =>
          onChange({ key: key as ChampionListSort, direction: defaultChampionDirection(key as ChampionListSort) })
        }
      >
        <SelectTrigger size="sm" className="min-w-32" aria-label="Sort by">
          <SelectValue />
        </SelectTrigger>
        <SelectContent position="popper" align="start">
          {CHAMPION_SORT_MENU.map((key) => (
            <SelectItem key={key} value={key}>
              {CHAMPION_SORT_LABELS[key]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        variant="outline"
        size="icon-sm"
        onClick={() => onChange({ key: sort.key, direction: ascending ? "desc" : "asc" })}
        aria-label={ascending ? "Sorted ascending. Switch to descending" : "Sorted descending. Switch to ascending"}
      >
        {ascending ? <ArrowUpNarrowWide aria-hidden="true" /> : <ArrowDownWideNarrow aria-hidden="true" />}
      </Button>
    </div>
  );
}
