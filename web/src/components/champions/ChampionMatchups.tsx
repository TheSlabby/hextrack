import { useMemo } from "react";
import { ShieldAlert, Swords, ThumbsUp, Users } from "lucide-react";

import type { ChampionLaneMatchups } from "@/api/types";
import { championDisplayName } from "@/lib/champions";
import { plural } from "@/lib/format";
import { POSITION_LONG_LABELS } from "@/lib/positions";

import { DetailCard, EmptyNote } from "./DetailCard";
import { matchupLists } from "./detailModel";
import { LaneMatchupList, type MatchupLinkFilters } from "./LaneMatchupList";

/** Lane matchups: best against, worst against and most common opponents in the same role. */
export function ChampionMatchups({
  matchups,
  champion,
  filters,
}: {
  matchups: ChampionLaneMatchups;
  /** Data Dragon key of this champion. */
  champion: string;
  filters: MatchupLinkFilters;
}) {
  const lists = useMemo(() => matchupLists(matchups.rows), [matchups.rows]);
  const name = championDisplayName(champion);
  const lane = filters.role ? POSITION_LONG_LABELS[filters.role].toLowerCase() : "lane";
  const min = plural(matchups.min_games, "time");

  return (
    <DetailCard
      eyebrow="Matchups"
      title="Lane opponents"
      icon={Swords}
      description={`${name} against the enemy champion in the same role.`}
    >
      {matchups.rows.length > 0 ? (
        <div className="flex flex-col gap-4">
          <div className="grid gap-4 lg:grid-cols-3">
            <LaneMatchupList
              title="Best against"
              icon={ThumbsUp}
              rows={lists.best}
              filters={filters}
              empty="No clear favourite yet."
            />
            <LaneMatchupList
              title="Worst against"
              icon={ShieldAlert}
              rows={lists.worst}
              filters={filters}
              empty="No clear counter yet."
            />
            <LaneMatchupList
              title="Most common"
              icon={Users}
              rows={lists.common}
              filters={filters}
              empty="No opponent met often enough yet."
            />
          </div>
          <p className="text-xs leading-relaxed text-text-muted">
            Opponents met at least {min} in {lane}. Best and worst are ranked by a win rate pulled toward {name}&apos;s
            average in this role, so a short streak can&apos;t top the list. Gold is the average gap to the lane opponent at
            the end of the game.
          </p>
        </div>
      ) : (
        <EmptyNote>
          No opponent has been met {min} in {lane} yet. A wider patch window has more games.
        </EmptyNote>
      )}
    </DetailCard>
  );
}
