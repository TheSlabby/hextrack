import { Link } from "@tanstack/react-router";
import { Crown } from "lucide-react";

import { EmptyState } from "@/components/common/EmptyState";
import { GlowCard } from "@/components/common/GlowCard";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { SectionHeader } from "@/components/common/SectionHeader";
import { StandingBadge } from "@/components/leaderboard/parts";
import { InGameDot } from "@/components/live/InGameDot";
import { useLivePuuids } from "@/components/live/useLivePuuids";
import { cn } from "@/lib/cn";
import { CHART_COLORS } from "@/lib/chartTheme";
import { formatPercent, plural } from "@/lib/format";
import { formatRiotId, summonerParams } from "@/lib/riotId";

import { CARRY_MIN_GAMES, gapText, type CarryStanding } from "./model";

/** The bar spans 50% ± this many points; shares further out are clamped. */
const BAR_HALF_RANGE = 0.25;

/** Diverging bar around 50%: teal to the right when a player outscored more often, red to the left. */
function ShareBar({ rate, muted }: { rate: number; muted: boolean }) {
  const offset = Math.max(-BAR_HALF_RANGE, Math.min(BAR_HALF_RANGE, rate - 0.5));
  const width = `${(Math.abs(offset) / BAR_HALF_RANGE) * 50}%`;
  const color = muted ? CHART_COLORS.neutral : offset >= 0 ? CHART_COLORS.positive : CHART_COLORS.negative;
  return (
    <span className="relative block h-1.5 w-full rounded-full bg-white/6" aria-hidden="true">
      {offset !== 0 ? (
        <span
          className={cn("absolute inset-y-0", offset > 0 ? "left-1/2 rounded-r-full" : "right-1/2 rounded-l-full")}
          style={{ width, backgroundColor: color }}
        />
      ) : null}
      <span className="absolute -top-0.5 left-1/2 h-2.5 w-px -translate-x-1/2 bg-white/30" />
    </span>
  );
}

/** Carry rate: share of scored duo games in which each player had the higher AI Score. */
export function CarryRankingCard({
  standings,
  labels,
  className,
}: {
  standings: readonly CarryStanding[];
  labels: ReadonlyMap<string, string>;
  className?: string;
}) {
  // Qualified players come first (carryStandings), so their position is their standing.
  const rows = standings.filter((standing) => standing.rate !== null);
  const live = useLivePuuids();
  return (
    <GlowCard className={cn("flex flex-col gap-3 p-4 sm:p-5", className)}>
      <SectionHeader
        size="sm"
        icon={Crown}
        eyebrow="Who carries whom"
        title="Carry rate"
        description="How often each player had the higher AI Score than their squad teammate."
      />
      {rows.length === 0 ? (
        <EmptyState compact tone="ai" icon={Crown} title="No scored duo games yet" />
      ) : (
        <ol className="flex flex-col divide-y divide-border">
          {rows.map((standing, index) => {
            const { player } = standing;
            const rate = standing.rate ?? 0;
            const standingNumber = standing.qualified ? index + 1 : null;
            const name = labels.get(player.puuid) ?? player.game_name;
            return (
              <li
                key={player.puuid}
                className="grid grid-cols-[28px_minmax(0,1fr)_6.5rem] items-center gap-x-3 py-2 first:pt-0 last:pb-0"
              >
                <StandingBadge standing={standingNumber} />
                <div className="flex min-w-0 flex-col gap-1.5">
                  <Link
                    to="/summoner/$region/$riotId"
                    params={summonerParams(player.game_name, player.tag_line)}
                    title={formatRiotId(player.game_name, player.tag_line)}
                    className="focus-ring flex min-w-0 items-center gap-2 self-start rounded-md transition-colors hover:text-gold-bright"
                  >
                    <ProfileIcon iconId={player.profile_icon_id} size="xs" alt="" />
                    <span className="truncate text-sm font-semibold">{name}</span>
                    <InGameDot live={live.has(player.puuid)} />
                  </Link>
                  <ShareBar rate={rate} muted={!standing.qualified} />
                </div>
                <div className="flex min-w-0 flex-col items-end leading-tight" aria-hidden="true">
                  <span
                    className={cn(
                      "font-display text-base font-semibold tabular-nums",
                      standing.qualified ? "text-text" : "text-text-secondary",
                    )}
                  >
                    {formatPercent(rate)}
                  </span>
                  <span className="text-[11px] text-text-secondary tabular-nums">
                    {standing.qualified ? (
                      <>
                        of {standing.scored}
                        {standing.avgDiff !== null ? ` · ${gapText(standing.avgDiff)} pts` : null}
                      </>
                    ) : (
                      `${plural(standing.scored, "game")}, too few`
                    )}
                  </span>
                </div>
                <span className="sr-only">
                  {standing.qualified ? "" : "Not ranked: "}
                  {name} had the higher AI Score in {standing.higher} of {plural(standing.scored, "duo game")}
                  {standing.avgDiff !== null ? `, ${gapText(standing.avgDiff)} points on average` : ""}.
                </span>
              </li>
            );
          })}
        </ol>
      )}
      <p className="text-xs leading-relaxed text-text-muted">
        Ranked from {CARRY_MIN_GAMES} scored duo games. "of" is the number of duo games (a game with two squad teammates
        counts once for each), and pts the average AI Score gap to the teammate.
      </p>
    </GlowCard>
  );
}
