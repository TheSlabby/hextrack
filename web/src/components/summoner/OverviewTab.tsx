import { ArrowRight, Sparkles } from "lucide-react";

import type { SummonerProfile } from "@/api/types";
import { AiTrendChart } from "@/components/ai/AiTrendChart";
import { GlowCard, SectionHeader, Stagger, StaggerItem } from "@/components/common";
import { Button } from "@/components/ui/button";

import { SEASON_GRID } from "./layout";
import { LpJourneyCard } from "./LpJourneyCard";
import { RecentFormCard } from "./RecentFormCard";
import { RecentGamesCard } from "./RecentGamesCard";
import { SeasonCards } from "./SeasonCards";

export interface OverviewTabProps {
  profile: SummonerProfile;
  onShowMatches: () => void;
  onShowAi: () => void;
  /** Below lg the sidebar is gone, so the season cards live at the end of this tab. */
  showSeasonCards?: boolean;
}

/** Overview tab: LP journey, compact AI trend, recent form and the latest games. */
export function OverviewTab({ profile, onShowMatches, onShowAi, showSeasonCards = false }: OverviewTabProps) {
  // With no ranked game this season the trend and form cards would only repeat "nothing yet",
  // so the season card (which says it once) leads and they stay out of the way.
  const noRankedGames = profile.stats.games === 0;
  const showLp = !noRankedGames || Boolean(profile.solo || profile.flex);
  const seasonCards = showSeasonCards ? <SeasonCards profile={profile} className={SEASON_GRID} /> : null;

  return (
    <Stagger className="flex flex-col gap-6">
      {noRankedGames && seasonCards ? <StaggerItem className="min-w-0">{seasonCards}</StaggerItem> : null}

      {showLp ? (
        <StaggerItem>
          <LpJourneyCard profile={profile} />
        </StaggerItem>
      ) : null}

      {noRankedGames ? null : (
        <StaggerItem className="grid gap-6 md:grid-cols-2">
          <GlowCard glow="cyan" className="flex min-w-0 flex-col gap-3 p-4 sm:p-5">
            <SectionHeader
              title={
                <span className="inline-flex items-center gap-2">
                  <Sparkles className="size-4 text-cyan" aria-hidden="true" />
                  AI Score trend
                </span>
              }
              eyebrow="Per-game scores"
              size="sm"
              action={
                <Button variant="ghost" size="xs" onClick={onShowAi} className="text-cyan hover:bg-cyan/10 hover:text-cyan">
                  Insights
                  <ArrowRight aria-hidden="true" />
                </Button>
              }
            />
            <div className="min-w-0 flex-1">
              <AiTrendChart puuid={profile.puuid} compact bare />
            </div>
          </GlowCard>
          <RecentFormCard form={profile.recent_form} className="h-full" />
        </StaggerItem>
      )}

      <StaggerItem>
        <RecentGamesCard puuid={profile.puuid} onSeeAll={onShowMatches} />
      </StaggerItem>

      {!noRankedGames && seasonCards ? <StaggerItem className="min-w-0">{seasonCards}</StaggerItem> : null}
    </Stagger>
  );
}
