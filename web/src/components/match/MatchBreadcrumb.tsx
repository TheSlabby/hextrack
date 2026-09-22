import { Link } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight, Home } from "lucide-react";

import type { MatchDetail } from "@/api/types";
import { Skeleton } from "@/components/ui/skeleton";
import { formatShortDate } from "@/lib/format";
import { summonerParams } from "@/lib/riotId";

import type { FocusPlayer } from "./focus";

const CRUMB_LINK =
  "inline-flex min-w-0 items-center gap-1.5 rounded-md py-1 text-text-secondary transition-colors hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold";

/**
 * "← Player#TAG › Ranked Solo/Duo · Sep 21" when the page was opened from a player's
 * history (`?player=`), otherwise "Home › Match".
 */
export function MatchBreadcrumb({
  matchId,
  match,
  focus,
  hasPlayerParam = false,
  loading = false,
}: {
  matchId: string;
  match: MatchDetail | undefined;
  focus: FocusPlayer | null;
  /** `?player=` is present (a puuid can only be resolved once the match loads). */
  hasPlayerParam?: boolean;
  /** The match query is still loading. */
  loading?: boolean;
}) {
  const riotId = focus?.riotId ?? null;
  const resolving = hasPlayerParam && loading;
  return (
    <nav aria-label="Breadcrumb" className="min-w-0">
      <ol className="flex min-w-0 items-center gap-1.5 text-sm">
        <li className="min-w-0 shrink">
          {!riotId && resolving ? (
            <span className="inline-flex items-center gap-1.5 py-1">
              <ChevronLeft className="size-4 shrink-0 text-gold" aria-hidden="true" />
              <Skeleton className="h-3.5 w-28" />
            </span>
          ) : riotId ? (
            <Link
              to="/summoner/$region/$riotId"
              params={summonerParams(riotId.gameName, riotId.tagLine)}
              search={{ tab: "matches" }}
              className={CRUMB_LINK}
            >
              <ChevronLeft className="size-4 shrink-0 text-gold" aria-hidden="true" />
              <span className="truncate font-medium text-text">{riotId.gameName}</span>
              <span className="shrink-0 text-text-muted">#{riotId.tagLine}</span>
              <span className="sr-only">, match history</span>
            </Link>
          ) : (
            <Link to="/" className={CRUMB_LINK}>
              <Home className="size-4 shrink-0 text-gold" aria-hidden="true" />
              <span>Home</span>
            </Link>
          )}
        </li>
        <li aria-hidden="true" className="shrink-0 text-text-muted">
          <ChevronRight className="size-3.5" />
        </li>
        <li aria-current="page" className="min-w-0 truncate text-text">
          {match ? (
            <>
              {match.queue_label}
              <span className="text-text-muted"> · {formatShortDate(match.game_start)}</span>
            </>
          ) : loading ? (
            <Skeleton className="inline-block h-3.5 w-36 align-middle" />
          ) : (
            <span className="tabular-nums">Match {matchId}</span>
          )}
        </li>
      </ol>
    </nav>
  );
}
