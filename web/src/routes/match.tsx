import { useMemo } from "react";
import { getRouteApi } from "@tanstack/react-router";

import { useMatch } from "@/api/queries";
import type { MatchDetail } from "@/api/types";
import { resolveFocusPlayer, type FocusPlayer } from "@/components/match/focus";
import { MatchBreadcrumb } from "@/components/match/MatchBreadcrumb";
import { MatchDetailView } from "@/components/match/MatchDetail";
import { OUTCOME_LABEL, outcomeOf } from "@/components/match/matchUtils";
import { formatShortDate } from "@/lib/format";
import { pageTitle, useDocumentTitle } from "@/lib/hooks";
import { championDisplayName } from "@/lib/champions";

const route = getRouteApi("/match/$matchId");

function matchPageTitle(matchId: string, match: MatchDetail | undefined, focus: FocusPlayer | null): string {
  if (!match) return pageTitle(`Match ${matchId}`);
  const player = focus?.participant;
  if (player) {
    const name = focus.riotId?.gameName ?? championDisplayName(player.champion_name);
    const outcome = OUTCOME_LABEL[outcomeOf(match.remake, player.win)];
    return pageTitle(name, `${championDisplayName(player.champion_name)} ${outcome}`, match.queue_label);
  }
  return pageTitle(match.queue_label, formatShortDate(match.game_start));
}

/** /match/$matchId: full match detail, with a breadcrumb back to `?player=` when present. */
export function MatchPage() {
  const { matchId } = route.useParams();
  const { player } = route.useSearch();
  // Same query (and cache entry) as MatchDetailView; used for the breadcrumb, title and focus.
  const { data: match, isPending } = useMatch(matchId);
  const focus = useMemo(() => resolveFocusPlayer(player, match), [player, match]);

  useDocumentTitle(matchPageTitle(matchId, match, focus));

  return (
    <div className="flex min-w-0 flex-col gap-4 sm:gap-5">
      <MatchBreadcrumb matchId={matchId} match={match} focus={focus} hasPlayerParam={Boolean(player)} loading={isPending} />
      <MatchDetailView matchId={matchId} focusPuuid={focus?.puuid ?? undefined} />
    </div>
  );
}
