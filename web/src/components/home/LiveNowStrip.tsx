import { Fragment } from "react";
import { Link } from "@tanstack/react-router";

import { useLiveGames } from "@/api/queries";
import type { LiveGame, LiveParticipant } from "@/api/types";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { GlowCard } from "@/components/common/GlowCard";
import { SectionHeader } from "@/components/common/SectionHeader";
import { LiveDot } from "@/components/live/LiveDot";
import { LiveTimer } from "@/components/live/LiveTimer";
import { partyLabel, rosterByTeam } from "@/components/live/model";
import { championDisplayName } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { plural } from "@/lib/format";
import { queueShortLabel } from "@/lib/queues";

/** One column on phones, two from md, three from xl. */
const GRID = "grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3";

function queueOf(game: LiveGame): string {
  return game.queue_id !== null ? queueShortLabel(game.queue_id, game.game_mode) : game.queue_label;
}

function playerName(p: LiveParticipant): string {
  return p.game_name ?? (p.champion_name ? championDisplayName(p.champion_name) : "Unknown");
}

/**
 * Home page: the roster's games in progress right now, one card each, linking to the live game
 * page. Renders nothing when nobody is in game (or the worker has never checked).
 */
export function LiveNowStrip() {
  const { data } = useLiveGames();
  if (!data || data.checked_at === null || data.games.length === 0) return null;
  const games = data.games;

  return (
    <section aria-labelledby="live-now" className="flex flex-col gap-4">
      <SectionHeader
        title={
          <span id="live-now" className="inline-flex items-center gap-2.5">
            <LiveDot size="md" showLabel={false} />
            Live now
          </span>
        }
        description={`${plural(games.length, "game")} in progress. Open one for both teams' ranks and form.`}
      />
      <ul className={GRID}>
        {games.map((game) => (
          <li key={game.game_id} className="min-w-0">
            <LiveGameCard game={game} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function LiveGameCard({ game }: { game: LiveGame }) {
  const teams = rosterByTeam(game);
  const queue = queueOf(game);
  const label = [
    `Live, ${queue}`,
    teams
      .map((team) =>
        team.players
          .map((p) => (p.champion_name ? `${playerName(p)} as ${championDisplayName(p.champion_name)}` : playerName(p)))
          .join(", "),
      )
      .join(" versus "),
    "Open the live game",
  ].join(". ");

  return (
    <GlowCard
      asChild
      interactive
      className={cn(
        "flex h-full flex-col gap-3 bg-gradient-to-br from-loss/[0.08] via-loss/[0.02] to-transparent p-4",
        "border-loss/20 hover:border-loss/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
      )}
    >
      <Link to="/live/$gameId" params={{ gameId: String(game.game_id) }} aria-label={label}>
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <LiveDot size="sm" />
            <span className="truncate text-sm font-semibold text-text">{queue}</span>
          </div>
          <LiveTimer game={game} className="shrink-0 font-display text-sm font-semibold text-text" />
        </div>

        <div className="flex flex-col gap-2">
          {teams.map((team, i) => (
            <Fragment key={team.teamId}>
              {i > 0 ? (
                <div className="flex items-center gap-2" aria-hidden="true">
                  <span className="h-px flex-1 bg-border" />
                  <span className="label-caps text-text-muted">vs</span>
                  <span className="h-px flex-1 bg-border" />
                </div>
              ) : null}
              <div className="flex min-w-0 items-start gap-2">
                <ul className="flex min-w-0 flex-1 flex-wrap gap-x-3 gap-y-1.5">
                  {team.players.map((p, j) => (
                    <li key={p.puuid ?? j} className="flex min-w-0 items-center gap-1.5">
                      <ChampionIcon champion={p.champion_name ?? ""} size="sm" />
                      <span className="truncate text-sm text-text-secondary">{playerName(p)}</span>
                    </li>
                  ))}
                </ul>
                {team.players.length >= 2 ? (
                  <span className="mt-1 inline-flex h-5 shrink-0 items-center rounded-full border border-border-strong bg-surface-2 px-2 text-[11px] font-semibold text-text-secondary">
                    {partyLabel(team.players.length)}
                  </span>
                ) : null}
              </div>
            </Fragment>
          ))}
        </div>
      </Link>
    </GlowCard>
  );
}
