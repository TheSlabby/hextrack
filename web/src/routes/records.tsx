/**
 * /records: single-game records for the roster (or one player), the AI Score record and the
 * pentakill hall of fame. Filters live in the URL (`?since=all&queue=solo&player=<puuid>`;
 * defaults omitted, like the leaderboard).
 */
import { useCallback, useMemo } from "react";
import { getRouteApi, Link } from "@tanstack/react-router";
import { CalendarDays, ExternalLink, Medal, Users } from "lucide-react";

import { useMeta, useRecords, useRoster } from "@/api/queries";
import type { LeaderboardQueue, Records, RosterEntry, StatsSince } from "@/api/types";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { GlowCard } from "@/components/common/GlowCard";
import { Reveal, Stagger, StaggerItem } from "@/components/common/Motion";
import { SectionHeader } from "@/components/common/SectionHeader";
import { QueueToggle } from "@/components/leaderboard/QueueToggle";
import { PentakillHallOfFame, QuadrakillList } from "@/components/records/PentakillHallOfFame";
import { PlayerFilter, type PlayerChip } from "@/components/records/PlayerFilter";
import { AiScoreRecordCard, RecordCard } from "@/components/records/RecordCard";
import {
  buildPlayerLookup,
  categoriesByKey,
  playerLabel,
  QUEUE_CAPTION,
  RECORD_GRID_ORDER,
  type PlayerLookup,
} from "@/components/records/recordMeta";
import { RecordsSkeleton } from "@/components/records/RecordsSkeleton";
import { SinceToggle } from "@/components/squad/SinceToggle";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { formatDate, plural } from "@/lib/format";
import { pageTitle, useDocumentTitle } from "@/lib/hooks";
import { formatRiotId, summonerParams } from "@/lib/riotId";

const route = getRouteApi("/records");

/** Roster players by name (case-insensitive), as filter chips. */
function rosterChips(roster: readonly RosterEntry[], players: PlayerLookup): PlayerChip[] {
  return [...roster]
    .sort(
      (a, b) =>
        a.game_name.localeCompare(b.game_name, undefined, { sensitivity: "base" }) ||
        a.tag_line.localeCompare(b.tag_line, undefined, { sensitivity: "base" }),
    )
    .map((entry) => ({
      puuid: entry.puuid,
      label: playerLabel(players, entry),
      riotId: formatRiotId(entry.game_name, entry.tag_line),
      iconId: entry.profile_icon_id,
    }));
}

interface SelectedPlayer {
  puuid: string;
  gameName: string | null;
  tagLine: string | null;
}

/** Name of the selected player: from the roster, else from any of their record entries. */
function selectedPlayer(puuid: string | null, roster: readonly RosterEntry[], data: Records | undefined): SelectedPlayer | null {
  if (!puuid) return null;
  const tracked = roster.find((entry) => entry.puuid === puuid);
  if (tracked) return { puuid, gameName: tracked.game_name, tagLine: tracked.tag_line };
  if (data?.puuid === puuid) {
    const entry = data.categories.flatMap((category) => category.entries).find((e) => e.puuid === puuid);
    if (entry) return { puuid, gameName: entry.game_name, tagLine: entry.tag_line };
  }
  return { puuid, gameName: null, tagLine: null };
}

function FilterCaption({
  since,
  queue,
  seasonStart,
  player,
  rosterSize,
  loading,
}: {
  since: StatsSince;
  queue: LeaderboardQueue;
  seasonStart: string | undefined;
  player: SelectedPlayer | null;
  rosterSize: number | undefined;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="flex h-5 items-center gap-3" aria-hidden="true">
        <Skeleton className="h-3.5 w-40" />
        <Skeleton className="h-3.5 w-32" />
      </div>
    );
  }
  return (
    <p className="flex min-h-5 flex-wrap items-center gap-x-4 gap-y-1 text-sm text-text-secondary">
      <span className="inline-flex items-center gap-1.5">
        <CalendarDays className="size-4 text-text-muted" aria-hidden="true" />
        {since === "season" && seasonStart ? (
          <>
            Season since <span className="font-medium text-text">{formatDate(seasonStart)}</span>
          </>
        ) : since === "season" ? (
          "This season"
        ) : (
          "Every stored game"
        )}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <Users className="size-4 text-text-muted" aria-hidden="true" />
        {player ? (
          <span className="font-medium text-text">
            {player.gameName && player.tagLine ? formatRiotId(player.gameName, player.tagLine) : "One player"}
          </span>
        ) : rosterSize !== undefined ? (
          plural(rosterSize, "tracked player")
        ) : (
          "The roster"
        )}
        <span>· {QUEUE_CAPTION[queue]}</span>
      </span>
    </p>
  );
}

function RecordsBody({ data, players }: { data: Records; players: PlayerLookup }) {
  const byKey = useMemo(() => categoriesByKey(data.categories), [data.categories]);
  const aiRecord = byKey.get("highest_ai_score");
  return (
    <div className="flex flex-col gap-6">
      <Stagger className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {RECORD_GRID_ORDER.map((key) => {
          const category = byKey.get(key);
          if (!category) return null;
          return (
            <StaggerItem key={key} className="min-w-0">
              <RecordCard category={category} scope={data.scope} players={players} />
            </StaggerItem>
          );
        })}
        {aiRecord ? (
          <StaggerItem className="min-w-0 sm:col-span-2 xl:col-span-4">
            <AiScoreRecordCard
              category={aiRecord}
              scope={data.scope}
              players={players}
              modelVersion={data.model_version}
            />
          </StaggerItem>
        ) : null}
      </Stagger>

      {data.scope === "roster" ? (
        <Reveal className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <PentakillHallOfFame pentakills={data.pentakills} scope={data.scope} since={data.since} players={players} />
          <QuadrakillList quadrakills={data.quadrakills} since={data.since} players={players} />
        </Reveal>
      ) : (
        // One player: a ranked bar list would compare them with no one, so their quadra
        // kills are a line in the hall of fame's header instead.
        <Reveal>
          <PentakillHallOfFame
            pentakills={data.pentakills}
            scope={data.scope}
            since={data.since}
            players={players}
            quadrakills={data.quadrakills.reduce((sum, row) => sum + row.count, 0)}
          />
        </Reveal>
      )}

      <p className="text-xs leading-relaxed text-text-muted">
        Only ranked games count (the queue filter above picks Solo/Duo, Flex or both); remakes are left out, and a
        record has to be above zero. Ties go to the earlier game. Best KDA is (kills + assists) / deaths (at least 1) and needs 5 takedowns; kill
        participation only counts games where the team got 10 or more kills. Longest game and fastest win list each
        match once. Highest AI Score only counts games scored by the current model. Names are current Riot IDs.
      </p>
    </div>
  );
}

export function RecordsPage() {
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const since: StatsSince = search.since ?? "season";
  const queue: LeaderboardQueue = search.queue ?? "all";
  const playerId = search.player ?? null;

  const meta = useMeta();
  const roster = useRoster();
  const query = useRecords({ since, queue, puuid: playerId, limit: 3 });
  const { data } = query;

  const rosterEntries = useMemo(() => roster.data ?? [], [roster.data]);
  const players = useMemo(() => buildPlayerLookup(rosterEntries), [rosterEntries]);
  const chips = useMemo(() => rosterChips(rosterEntries, players), [rosterEntries, players]);
  const player = selectedPlayer(playerId, rosterEntries, data);
  useDocumentTitle(pageTitle(player?.gameName ? `${player.gameName}'s records` : "Records"));

  // An untracked player (linked from their profile) gets a chip of their own.
  const allChips = useMemo(() => {
    if (!player || chips.some((chip) => chip.puuid === player.puuid)) return chips;
    const extra: PlayerChip = {
      puuid: player.puuid,
      label: player.gameName ?? "This player",
      riotId: player.gameName && player.tagLine ? formatRiotId(player.gameName, player.tagLine) : "This player",
      iconId: null,
    };
    return [extra, ...chips];
  }, [chips, player]);

  const setFilters = useCallback(
    (next: { since?: StatsSince; queue?: LeaderboardQueue; player?: string | null }) =>
      void navigate({
        search: (prev) => {
          const result = { ...prev };
          if (next.since !== undefined) result.since = next.since === "season" ? undefined : next.since;
          if (next.queue !== undefined) result.queue = next.queue === "all" ? undefined : next.queue;
          if (next.player !== undefined) result.player = next.player ?? undefined;
          return result;
        },
        replace: true,
      }),
    [navigate],
  );

  const refetching = query.isPlaceholderData;

  let body;
  if (query.isPending) {
    body = <RecordsSkeleton />;
  } else if (query.isError && !data) {
    body = (
      <GlowCard>
        <ErrorState
          error={query.error}
          title={playerId ? "Couldn't load this player's records" : "Couldn't load the records"}
          onRetry={() => void query.refetch()}
          action={
            playerId ? (
              <Button variant="outline" size="sm" onClick={() => setFilters({ player: null })}>
                <Users aria-hidden="true" />
                Show the whole roster
              </Button>
            ) : null
          }
        />
      </GlowCard>
    );
  } else if (data) {
    const empty = data.categories.every((category) => category.entries.length === 0);
    body = (
      <div
        className={cn("transition-opacity duration-200", refetching && "pointer-events-none opacity-60")}
        aria-busy={refetching || undefined}
      >
        {empty ? (
          <GlowCard>
            <EmptyState
              icon={Medal}
              title={`No ranked games${player ? ` for ${player.gameName ?? "this player"}` : ""} ${since === "season" ? "this season" : "yet"}`}
              description={
                since === "season"
                  ? "Records only count ranked games. Older games may still hold some: try All time."
                  : "Records appear once ranked games are stored."
              }
              action={
                <>
                  {since === "season" ? (
                    <Button variant="outline" size="sm" onClick={() => setFilters({ since: "all" })}>
                      Show all time
                    </Button>
                  ) : null}
                  {playerId ? (
                    <Button variant="ghost" size="sm" onClick={() => setFilters({ player: null })}>
                      <Users aria-hidden="true" />
                      Everyone's records
                    </Button>
                  ) : null}
                </>
              }
            />
          </GlowCard>
        ) : (
          <RecordsBody data={data} players={players} />
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Reveal>
        <div className="flex flex-col gap-4">
          <SectionHeader
            as="h1"
            size="lg"
            eyebrow="The Squad"
            icon={Medal}
            title="Records"
            description={
              player
                ? "One player's best single games. Every record links to its match."
                : "The roster's best single games. Every record links to its match."
            }
            action={
              <>
                <SinceToggle value={since} onChange={(next) => setFilters({ since: next })} />
                <QueueToggle value={queue} onChange={(next) => setFilters({ queue: next })} />
              </>
            }
          />
          <FilterCaption
            since={since}
            queue={queue}
            seasonStart={meta.data?.season_start}
            player={player}
            rosterSize={roster.data?.length}
            loading={query.isPending && meta.isPending}
          />
          <div className="flex flex-col gap-2">
            <PlayerFilter
              players={allChips}
              selected={playerId}
              onSelect={(puuid) => setFilters({ player: puuid })}
              loading={roster.isPending}
            />
            {player?.gameName && player.tagLine ? (
              <Link
                to="/summoner/$region/$riotId"
                params={summonerParams(player.gameName, player.tagLine)}
                className="inline-flex w-fit items-center gap-1.5 rounded-sm text-xs font-medium text-gold transition-colors hover:text-gold-bright focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold"
              >
                <ExternalLink className="size-3.5" aria-hidden="true" />
                Open {player.gameName}'s profile
              </Link>
            ) : null}
          </div>
        </div>
      </Reveal>
      {body}
    </div>
  );
}
