import type { LucideIcon } from "lucide-react";

import type { ChampionLaneMatchup, ChampionRole, LeaderboardQueue } from "@/api/types";
import { MatchupRow } from "@/components/common/MatchupRow";
import { plural } from "@/lib/format";

import { EmptyNote } from "./DetailCard";

/** Filters carried over to the opponent's page (same window, same queue, same lane). */
export interface MatchupLinkFilters {
  patch: string;
  queue: LeaderboardQueue;
  role: ChampionRole | null;
}

/** One titled list of lane opponents (best / worst / most common). */
export function LaneMatchupList({
  title,
  icon: Icon,
  rows,
  filters,
  empty,
}: {
  title: string;
  icon: LucideIcon;
  rows: readonly ChampionLaneMatchup[];
  filters: MatchupLinkFilters;
  empty: string;
}) {
  const linkSearch = {
    patch: filters.patch === "recent" ? undefined : filters.patch,
    queue: filters.queue === "all" ? undefined : filters.queue,
    role: filters.role ?? undefined,
  };
  return (
    <section aria-label={title} className="flex min-w-0 flex-col gap-2">
      <h3 className="label-caps flex items-center gap-1.5">
        <Icon className="size-3.5" aria-hidden="true" />
        {title}
      </h3>
      {rows.length === 0 ? (
        <EmptyNote>{empty}</EmptyNote>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {rows.map((row) => (
            <li key={row.champion_id}>
              <MatchupRow
                champion={row.champion_name}
                wins={row.wins}
                losses={row.games - row.wins}
                avgGoldDiff={row.avg_gold_diff}
                detail={<span>{plural(row.games, "game")}</span>}
                linkSearch={linkSearch}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
