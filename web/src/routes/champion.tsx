/**
 * /champions/$champion: one champion's stats by role, builds, runes, spells, skill order,
 * lane matchups and the squad on it. Patch / queue / role live in the URL (defaults omitted:
 * recent patches, all queues, the champion's most played role).
 */
import { useCallback, type ReactNode } from "react";
import { getRouteApi, Link } from "@tanstack/react-router";
import { CalendarRange, Hammer, SearchX, Swords, Users } from "lucide-react";

import { isApiError } from "@/api/client";
import { useChampion } from "@/api/queries";
import type { ChampionDetail, ChampionPatchParam, ChampionRole, LeaderboardQueue } from "@/api/types";
import { BuildPopular, ItemBuild } from "@/components/champions/BuildItems";
import { BuildCore } from "@/components/champions/BuildCore";
import { ChampionHeader } from "@/components/champions/ChampionHeader";
import { ChampionMatchups } from "@/components/champions/ChampionMatchups";
import { ChampionSquad } from "@/components/champions/ChampionSquad";
import { ChampionBuildSkeleton } from "@/components/champions/ChampionStatStrip";
import { RuneBuild } from "@/components/champions/RuneBuild";
import { SkillOrder } from "@/components/champions/SkillOrder";
import { SpellOptions } from "@/components/champions/SpellOptions";
import { DdragonPatch } from "@/components/common/DdragonPatch";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorState } from "@/components/common/ErrorState";
import { GlowCard } from "@/components/common/GlowCard";
import { Stagger, StaggerItem } from "@/components/common/Motion";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { championDisplayName, patchWindowLabel } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { pageTitle, useDocumentTitle } from "@/lib/hooks";
import type { ChampionTab } from "@/router";

const route = getRouteApi("/champions/$champion");

/** "monkeyking" -> "Monkeyking": a readable title until the API returns the real key. */
function slugTitle(slug: string): string {
  return slug ? slug.charAt(0).toUpperCase() + slug.slice(1) : "Champion";
}

/**
 * Build tab. Desktop: runes, spells and popular items on the left; core build, item build and
 * skill order on the right. Phones: one column, core build first.
 */
function BuildTab({ data }: { data: ChampionDetail }) {
  const detail = data.detail;
  if (!detail) return null;
  const timeline = detail.stats.timeline_games;
  // Items, spells and rune trees are drawn at the newest patch in the window.
  const newest = data.patches[0] ?? null;
  const resetKey = `${data.role}-${data.patch}-${data.queue}`;

  return (
    <DdragonPatch patch={newest}>
      <Stagger className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <StaggerItem className="order-2 flex min-w-0 flex-col gap-4 lg:order-1">
          <RuneBuild key={resetKey} runes={detail.runes} patch={newest} />
          <SpellOptions spells={detail.spells} />
          <BuildPopular builds={detail.builds} />
        </StaggerItem>
        <StaggerItem className="order-1 flex min-w-0 flex-col gap-4 lg:order-2">
          <BuildCore builds={detail.builds} timelineGames={timeline} />
          <ItemBuild builds={detail.builds} timelineGames={timeline} />
          <SkillOrder skills={detail.skills} champion={data.champion_name} timelineGames={timeline} />
        </StaggerItem>
      </Stagger>
    </DdragonPatch>
  );
}

function NoGames({
  data,
  patch,
  onPatchChange,
}: {
  data: ChampionDetail;
  patch: ChampionPatchParam;
  onPatchChange: (patch: ChampionPatchParam) => void;
}) {
  const name = championDisplayName(data.champion_name);
  return (
    <GlowCard>
      <EmptyState
        icon={CalendarRange}
        title={`No games on ${name} in ${patchWindowLabel(data.patch, data.patches)} yet`}
        description={
          patch === "season"
            ? "Nothing counted this season for this queue yet. Games are added as the worker counts them."
            : "The whole season has more games to go on."
        }
        action={patch !== "season" ? <Button onClick={() => onPatchChange("season")}>Show whole season</Button> : undefined}
      />
    </GlowCard>
  );
}

export function ChampionPage() {
  const { champion } = route.useParams();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const patch: ChampionPatchParam = search.patch ?? "recent";
  const queue: LeaderboardQueue = search.queue ?? "all";
  const role: ChampionRole | null = search.role ?? null;
  const tab: ChampionTab = search.tab ?? "build";

  const query = useChampion(champion, { patch, queue, role });
  const { data } = query;
  const refetching = query.isPlaceholderData;
  const key = data?.champion_name ?? null;
  useDocumentTitle(pageTitle(key ? championDisplayName(key) : slugTitle(champion)));

  // The API's default role is the most played one (roles come most played first).
  const defaultRole = data?.roles[0]?.position ?? null;
  const setPatch = useCallback(
    (next: ChampionPatchParam) =>
      void navigate({ search: (prev) => ({ ...prev, patch: next === "recent" ? undefined : next }), replace: true }),
    [navigate],
  );
  const setQueue = useCallback(
    (next: LeaderboardQueue) =>
      void navigate({ search: (prev) => ({ ...prev, queue: next === "all" ? undefined : next }), replace: true }),
    [navigate],
  );
  const setRole = useCallback(
    (next: ChampionRole) =>
      void navigate({ search: (prev) => ({ ...prev, role: next === defaultRole ? undefined : next }), replace: true }),
    [navigate, defaultRole],
  );

  const setTab = useCallback(
    (next: string) => {
      if (next !== "build" && next !== "matchups" && next !== "squad") return;
      void navigate({ search: (prev) => ({ ...prev, tab: next === "build" ? undefined : next }), replace: true });
    },
    [navigate],
  );

  if (query.isError && !data) {
    const error = query.error;
    let card: ReactNode;
    if (isApiError(error) && (error.code === "champion_not_found" || error.status === 404)) {
      card = (
        <EmptyState
          icon={SearchX}
          title={`No champion data for “${champion}”`}
          description="Either the name is off, or nobody in our games has played it this season."
          action={
            <Button asChild>
              <Link to="/champions">Browse champions</Link>
            </Button>
          }
        />
      );
    } else if (isApiError(error) && error.code === "unknown_patch") {
      card = (
        <EmptyState
          icon={CalendarRange}
          title={`No games on patch ${patch}`}
          description="That patch has no counted games. The newest patches are the place to start."
          action={<Button onClick={() => setPatch("recent")}>Show recent patches</Button>}
        />
      );
    } else {
      card = <ErrorState error={error} title="Couldn't load this champion" onRetry={() => void query.refetch()} />;
    }
    return <GlowCard className="mx-auto mt-8 w-full max-w-xl">{card}</GlowCard>;
  }

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <ChampionHeader
        champion={key}
        detail={data}
        patch={patch}
        queue={queue}
        onPatchChange={setPatch}
        onQueueChange={setQueue}
        onRoleChange={setRole}
      />
      <Tabs value={tab} onValueChange={setTab} className="gap-4">
        <TabsList variant="line" aria-label="Champion sections" className="w-full justify-start gap-5 sm:gap-6">
          <TabsTrigger value="build">
            <Hammer aria-hidden="true" />
            Build
          </TabsTrigger>
          <TabsTrigger value="matchups">
            <Swords aria-hidden="true" />
            Matchups
          </TabsTrigger>
          <TabsTrigger value="squad">
            <Users aria-hidden="true" />
            Squad
          </TabsTrigger>
        </TabsList>
        <div
          className={cn("min-w-0 transition-opacity duration-200", refetching && "opacity-60")}
          aria-busy={refetching || undefined}
        >
          <TabsContent value="build" className="min-w-0">
            {!data ? (
              <ChampionBuildSkeleton />
            ) : data.detail ? (
              <BuildTab data={data} />
            ) : (
              <NoGames data={data} patch={patch} onPatchChange={setPatch} />
            )}
          </TabsContent>
          <TabsContent value="matchups" className="min-w-0">
            {!data ? (
              <ChampionBuildSkeleton />
            ) : data.detail ? (
              <DdragonPatch patch={data.patches[0] ?? null}>
                <ChampionMatchups
                  matchups={data.detail.matchups}
                  champion={data.champion_name}
                  filters={{ patch, queue, role: data.role }}
                />
              </DdragonPatch>
            ) : (
              <NoGames data={data} patch={patch} onPatchChange={setPatch} />
            )}
          </TabsContent>
          <TabsContent value="squad" className="min-w-0">
            {data ? <ChampionSquad champion={data.champion_name} queue={queue} /> : <ChampionBuildSkeleton />}
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
