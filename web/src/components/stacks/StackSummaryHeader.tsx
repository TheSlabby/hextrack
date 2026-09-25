/**
 * Headline numbers for the Stacks page: games, record, average game length and kills, then the
 * stack's recent form and current streak. Full width above the awards / lineups grid.
 */
import { Clock, Gamepad2, Swords, Trophy } from "lucide-react";

import type { StackSize, StackSummary } from "@/api/types";
import { FormDots } from "@/components/common/FormDots";
import { GlowCard } from "@/components/common/GlowCard";
import { StatTile } from "@/components/common/StatTile";
import { StreakBadge } from "@/components/common/StreakBadge";
import { WinRateBar } from "@/components/common/WinRateBar";
import { formatDecimal, formatDuration, formatDurationLong, formatInteger, formatPercent } from "@/lib/format";

import { STACK_PERIOD_LABEL, stackLabelPlural } from "./model";

/** `recent_form` holds at most this many results (API contract), so a full list reads "20+". */
const STACK_FORM_LIMIT = 20;

/** Record tile: W-L big, then the split bar and the win rate (StatTile has no slot for a bar). */
function RecordTile({ wins, losses, winrate }: { wins: number; losses: number; winrate: number }) {
  const games = wins + losses;
  return (
    <GlowCard className="flex min-w-0 flex-col gap-1.5 p-4">
      <div className="flex items-center gap-1.5">
        <Trophy className="size-3.5 text-text-muted" aria-hidden="true" />
        <span className="label-caps truncate">Record</span>
      </div>
      <div className="font-display text-2xl leading-tight font-semibold tabular-nums sm:text-[28px]">
        <span className="text-win">{wins}W</span> <span className="text-loss">{losses}L</span>
      </div>
      <WinRateBar wins={wins} losses={losses} showLabels={false} size="sm" />
      <span className="text-xs text-text-secondary tabular-nums">
        {games > 0 ? `${formatPercent(winrate)} win rate` : "No games yet"}
      </span>
    </GlowCard>
  );
}

/** "24.1 – 18.3": team kills against enemy kills per game. */
function KillsValue({ team, enemy }: { team: number | null; enemy: number | null }) {
  if (team === null || enemy === null) return <span>–</span>;
  return (
    <span className="inline-flex items-baseline gap-1.5 text-xl sm:text-[28px]">
      <span aria-hidden="true">{formatDecimal(team)}</span>
      <span aria-hidden="true" className="text-text-muted">
        –
      </span>
      <span aria-hidden="true" className="text-text-secondary">
        {formatDecimal(enemy)}
      </span>
      <span className="sr-only">
        {formatDecimal(team)} team kills to {formatDecimal(enemy)} enemy kills per game
      </span>
    </span>
  );
}

export function StackSummaryHeader({ data }: { data: StackSummary }) {
  const size = data.size as StackSize;
  const losses = data.games - data.wins;
  const form = data.recent_form;
  const formWins = form.filter(Boolean).length;

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <StatTile
        label="Games"
        icon={Gamepad2}
        value={data.games}
        format={formatInteger}
        animate
        accent="gold"
        caption={`${stackLabelPlural(size)} · ${STACK_PERIOD_LABEL[data.since].toLowerCase()}`}
      />
      <RecordTile wins={data.wins} losses={losses} winrate={data.winrate} />
      <StatTile
        label="Avg game length"
        icon={Clock}
        value={
          data.avg_duration === null ? (
            "–"
          ) : (
            <>
              <span aria-hidden="true">{formatDuration(data.avg_duration)}</span>
              <span className="sr-only">{formatDurationLong(data.avg_duration)}</span>
            </>
          )
        }
        caption="Per stack game"
      />
      <StatTile
        label="Avg kills"
        icon={Swords}
        value={<KillsValue team={data.avg_team_kills} enemy={data.avg_enemy_kills} />}
        caption="Team vs enemy, per game"
      />

      <GlowCard className="col-span-2 flex flex-col gap-2 p-4 sm:flex-row sm:items-center sm:gap-4 md:col-span-4">
        <div className="flex shrink-0 items-baseline gap-2">
          <span className="label-caps">Recent form</span>
          {form.length > 0 ? (
            <span className="text-xs text-text-secondary tabular-nums">
              Last {form.length}: <span className="text-win">{formWins}W</span>{" "}
              <span className="text-loss">{form.length - formWins}L</span>
            </span>
          ) : null}
        </div>
        <FormDots results={form} limit={STACK_FORM_LIMIT} className="min-w-0 flex-1" />
        <StreakBadge results={form} limit={STACK_FORM_LIMIT} className="self-start sm:self-auto" />
      </GlowCard>
    </div>
  );
}
