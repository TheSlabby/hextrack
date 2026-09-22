import { BarChart3 } from "lucide-react";

import { useMeta } from "@/api/queries";
import type { SummonerProfile } from "@/api/types";
import { EmptyState, GlowCard, Stagger, StaggerItem } from "@/components/common";
import { cn } from "@/lib/cn";

import { ChampionsCard } from "./ChampionsCard";
import { RolesCard } from "./RolesCard";
import { SeasonStatsCard } from "./SeasonStatsCard";
import { UpdateButton } from "./UpdateButton";

export interface SeasonCardsProps {
  profile: SummonerProfile;
  /** Extra grid classes (the section is a single column by default). */
  className?: string;
}

/**
 * Season stats, most-played champions and roles. A player with no ranked games this season
 * gets one card explaining that instead of three identical empty ones.
 */
export function SeasonCards({ profile, className }: SeasonCardsProps) {
  const meta = useMeta();

  if (profile.stats.games === 0) {
    return (
      <Stagger className={cn("grid min-w-0 gap-4", className)}>
        <StaggerItem className="min-w-0 md:col-span-2 lg:col-span-1">
          <GlowCard className="flex flex-col p-4 sm:p-5">
            <EmptyState
              compact
              icon={BarChart3}
              title="No ranked games this season"
              description="Season stats, champions and roles cover Ranked Solo/Duo and Flex. They fill in after the first ranked game of the season."
              action={<UpdateButton profile={profile} variant="outline" />}
            />
          </GlowCard>
        </StaggerItem>
      </Stagger>
    );
  }

  return (
    <Stagger className={cn("grid min-w-0 gap-4", className)}>
      <StaggerItem className="min-w-0">
        <SeasonStatsCard stats={profile.stats} seasonStart={meta.data?.season_start} className="h-full" />
      </StaggerItem>
      <StaggerItem className="min-w-0">
        <ChampionsCard champions={profile.top_champions} className="h-full" />
      </StaggerItem>
      <StaggerItem className="min-w-0 md:col-span-2 lg:col-span-1">
        <RolesCard roles={profile.roles} className="h-full" />
      </StaggerItem>
    </Stagger>
  );
}
