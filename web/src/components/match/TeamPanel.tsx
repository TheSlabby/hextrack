import { useId } from "react";

import type { ParticipantSummary, TeamDetail } from "@/api/types";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { GlowCard } from "@/components/common/GlowCard";
import { ItemSlots } from "@/components/common/ItemSlots";
import { SpellIcons } from "@/components/common/SpellIcons";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { formatCompact, formatDecimal, formatInteger, formatPercent } from "@/lib/format";
import { positionLabel } from "@/lib/positions";
import { championDisplayName } from "@/lib/champions";

import { AiScoreWithRank, KdaLine, KdaRatio, PlayerNameLink, StatBar } from "./MatchBits";
import { TeamBans, TeamObjectives } from "./TeamObjectives";
import {
  OUTCOME_LABEL,
  OUTCOME_STYLES,
  outcomeOf,
  sortByPosition,
  TEAM_SIDE_LABEL,
  type MatchMaxima,
} from "./matchUtils";

export interface TeamPanelProps {
  team: TeamDetail;
  /** Both teams (for MVP / ACE). */
  teams: readonly TeamDetail[];
  remake: boolean;
  maxima: MatchMaxima;
  /** Minutes played (for per-minute captions). */
  minutes: number;
  focusPuuid?: string;
  /** Inside an expanded match row: a panel instead of a card. */
  embedded?: boolean;
}

const TAKEN_BAR = "bg-text-muted/60";

/** Tighter cell padding so all nine columns fit an ~820px panel; narrower containers scroll. */
const TABLE_DENSITY =
  "min-w-[800px] [&_td]:px-2 [&_th]:px-2 [&_td:first-child]:pl-3 [&_th:first-child]:pl-3 [&_td:last-child]:pr-3 [&_th:last-child]:pr-3";

function kpOf(p: ParticipantSummary): string {
  return formatPercent(p.kill_participation);
}

/** Totals for the footer row. */
function totals(players: readonly ParticipantSummary[]) {
  return players.reduce(
    (acc, p) => ({
      taken: acc.taken + p.damage_taken,
      cs: acc.cs + p.cs,
      vision: acc.vision + p.vision_score,
      wardsPlaced: acc.wardsPlaced + p.wards_placed,
      wardsKilled: acc.wardsKilled + p.wards_killed,
    }),
    { taken: 0, cs: 0, vision: 0, wardsPlaced: 0, wardsKilled: 0 },
  );
}

function PlayerCell({ p, focused }: { p: ParticipantSummary; focused: boolean }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <ChampionIcon champion={p.champion_name} size="sm" level={p.champ_level} highlight={focused} />
      {/* Spells only when the table has room (keeps it scroll-free inside a ~820px row). */}
      <SpellIcons spell1={p.summoner1_id} spell2={p.summoner2_id} size="sm" className="hidden @4xl:flex" />
      <div className="flex min-w-0 flex-col">
        {/* No fixed cap: the cell already clips (min-w-0 + truncate), so wide rows show the full name. */}
        <PlayerNameLink participant={p} focused={focused} showTrackedMark className="text-[13px]" />
        <span className="truncate text-[11px] text-text-muted">
          {p.team_position !== "UNKNOWN" ? `${positionLabel(p.team_position)} · ` : ""}
          {championDisplayName(p.champion_name)}
        </span>
      </div>
    </div>
  );
}

function TeamTable({ team, teams, remake, maxima, minutes, focusPuuid, players }: TeamPanelProps & { players: ParticipantSummary[] }) {
  const outcome = outcomeOf(remake, team.win);
  const style = OUTCOME_STYLES[outcome];
  const sum = totals(players);
  return (
    <Table className={TABLE_DENSITY} containerClassName="hidden @3xl:block">
      <TableHeader>
        <TableRow>
          <TableHead>Player</TableHead>
          <TableHead className="text-center">
            <span aria-hidden="true">AI</span>
            <span className="sr-only">AI Score</span>
          </TableHead>
          <TableHead>KDA</TableHead>
          <TableHead>Damage</TableHead>
          <TableHead>Taken</TableHead>
          <TableHead className="text-right">Gold</TableHead>
          <TableHead className="text-right">CS</TableHead>
          <TableHead className="text-right">Vision</TableHead>
          <TableHead>Items</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {players.map((p) => {
          const focused = p.puuid === focusPuuid;
          return (
            <TableRow
              key={p.puuid}
              data-state={focused ? "selected" : undefined}
              aria-current={focused ? "true" : undefined}
              className={cn(focused && "shadow-[inset_2px_0_0_var(--color-gold)]")}
            >
              <TableCell className="py-2">
                <PlayerCell p={p} focused={focused} />
              </TableCell>
              <TableCell className="py-2 text-center">
                <AiScoreWithRank participant={p} teams={teams} remake={remake} layout="stack" size="sm" />
              </TableCell>
              <TableCell className="py-2">
                <div className="flex flex-col gap-0.5">
                  <KdaLine kills={p.kills} deaths={p.deaths} assists={p.assists} className="text-[13px] font-semibold" />
                  <span className="text-[11px] text-text-muted">
                    <KdaRatio kda={p.kda} deaths={p.deaths} suffix="" className="text-[11px]" /> · {kpOf(p)} KP
                  </span>
                </div>
              </TableCell>
              <TableCell className="py-2">
                <StatBar
                  value={p.damage_to_champions}
                  max={maxima.damage}
                  label={formatInteger(p.damage_to_champions)}
                  barClassName={cn(style.bar, "opacity-85")}
                  className="w-[72px]"
                />
              </TableCell>
              <TableCell className="py-2">
                <StatBar
                  value={p.damage_taken}
                  max={maxima.taken}
                  label={formatCompact(p.damage_taken)}
                  barClassName={TAKEN_BAR}
                  className="w-11"
                />
              </TableCell>
              <TableCell className="py-2 text-right">
                <div className="flex flex-col">
                  <span className="text-xs font-medium text-text">{formatCompact(p.gold)}</span>
                  <span className="text-[11px] text-text-muted">{formatInteger(p.gold_per_min)}/m</span>
                </div>
              </TableCell>
              <TableCell className="py-2 text-right">
                <div className="flex flex-col">
                  <span className="text-xs font-medium text-text">{p.cs}</span>
                  <span className="text-[11px] text-text-muted">{formatDecimal(p.cs_per_min)}/m</span>
                </div>
              </TableCell>
              <TableCell className="py-2 text-right">
                <div className="flex flex-col" title="Wards placed / destroyed">
                  <span className="text-xs font-medium text-text">{p.vision_score}</span>
                  <span className="text-[11px] text-text-muted">
                    {p.wards_placed} / {p.wards_killed}
                  </span>
                </div>
              </TableCell>
              <TableCell className="py-2">
                <ItemSlots items={p.items} size="sm" />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
      <TableFooter className="bg-white/[0.02] text-xs">
        <TableRow className="hover:bg-transparent">
          <TableCell className="label-caps">Team total</TableCell>
          <TableCell />
          <TableCell>
            <KdaLine kills={team.kills} deaths={team.deaths} assists={team.assists} className="font-semibold" />
          </TableCell>
          <TableCell className="font-semibold text-text">{formatInteger(team.damage_to_champions)}</TableCell>
          <TableCell className="text-text-secondary">{formatCompact(sum.taken)}</TableCell>
          <TableCell className="text-right font-semibold text-text">{formatCompact(team.gold)}</TableCell>
          <TableCell className="text-right">
            <div className="flex flex-col">
              <span className="font-semibold text-text">{sum.cs}</span>
              <span className="text-[11px] text-text-muted">{formatDecimal(minutes > 0 ? sum.cs / minutes : 0)}/m</span>
            </div>
          </TableCell>
          <TableCell className="text-right">
            <div className="flex flex-col" title="Wards placed / destroyed">
              <span className="font-semibold text-text">{sum.vision}</span>
              <span className="text-[11px] text-text-muted">
                {sum.wardsPlaced} / {sum.wardsKilled}
              </span>
            </div>
          </TableCell>
          <TableCell />

        </TableRow>
      </TableFooter>
    </Table>
  );
}

function TeamList({ team, teams, remake, maxima, focusPuuid, players }: TeamPanelProps & { players: ParticipantSummary[] }) {
  const style = OUTCOME_STYLES[outcomeOf(remake, team.win)];
  const sum = totals(players);
  return (
    <div className="@3xl:hidden">
      <ul className="divide-y divide-border">
        {players.map((p) => {
          const focused = p.puuid === focusPuuid;
          return (
            <li
              key={p.puuid}
              aria-current={focused ? "true" : undefined}
              className={cn("flex flex-col gap-2 px-3 py-2.5", focused && "bg-gold/5 shadow-[inset_2px_0_0_var(--color-gold)]")}
            >
              <div className="flex min-w-0 items-center gap-2">
                <ChampionIcon champion={p.champion_name} size="sm" level={p.champ_level} highlight={focused} />
                <SpellIcons spell1={p.summoner1_id} spell2={p.summoner2_id} size="sm" />
                <div className="ml-0.5 flex min-w-0 flex-1 flex-col">
                  <PlayerNameLink participant={p} focused={focused} showTrackedMark className="text-[13px]" />
                  <span className="flex flex-wrap items-center gap-x-1.5 text-[11px] text-text-muted">
                    <KdaLine kills={p.kills} deaths={p.deaths} assists={p.assists} className="font-semibold" />
                    <span aria-hidden="true">·</span>
                    <KdaRatio kda={p.kda} deaths={p.deaths} suffix="" />
                  </span>
                </div>
                {/* Wider containers: items join the first line. */}
                <ItemSlots items={p.items} size="sm" className="mr-1 hidden @xl:flex" />
                <AiScoreWithRank participant={p} teams={teams} remake={remake} layout="stack" size="sm" />
              </div>
              <div className="flex flex-col gap-2 @xl:flex-row @xl:items-center @xl:gap-6">
                <div className="flex items-center gap-3 @xl:w-44 @xl:shrink-0">
                  <ItemSlots items={p.items} size="sm" className="@xl:hidden" />
                  <StatBar
                    value={p.damage_to_champions}
                    max={maxima.damage}
                    label={`${formatCompact(p.damage_to_champions)} dmg`}
                    barClassName={cn(style.bar, "opacity-85")}
                    className="min-w-0 flex-1"
                  />
                </div>
                <dl className="grid grid-cols-3 gap-x-3 gap-y-0.5 text-[11px] tabular-nums @xl:flex @xl:flex-wrap @xl:gap-x-4">
                  {[
                    ["KP", kpOf(p)],
                    ["CS", `${p.cs} (${formatDecimal(p.cs_per_min)})`],
                    ["Gold", formatCompact(p.gold)],
                    ["Taken", formatCompact(p.damage_taken)],
                    ["Vision", String(p.vision_score)],
                  ].map(([label, value]) => (
                    <div key={label} className="flex gap-1">
                      <dt className="text-text-muted">{label}</dt>
                      <dd className="text-text-secondary">{value}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border bg-white/[0.02] px-3 py-2 text-[11px] tabular-nums text-text-secondary">
        <span className="label-caps">Team total</span>
        <KdaLine kills={team.kills} deaths={team.deaths} assists={team.assists} className="font-semibold" />
        <span>{formatCompact(team.damage_to_champions)} dmg</span>
        <span>{formatCompact(team.gold)} gold</span>
        <span>{sum.cs} CS</span>
        <span>{sum.vision} vision</span>
      </div>
    </div>
  );
}

/**
 * One team's scoreboard: result + side header with objectives, a full table on wide
 * containers (a compact list on narrow ones), team totals and bans.
 */
export function TeamPanel(props: TeamPanelProps) {
  const { team, remake, embedded } = props;
  const headingId = useId();
  const outcome = outcomeOf(remake, team.win);
  const style = OUTCOME_STYLES[outcome];
  const players = sortByPosition(team.participants);

  const body = (
    <>
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border px-3 py-3 sm:px-4">
        <div className="flex min-w-0 items-center gap-2.5">
          <span aria-hidden="true" className={cn("h-5 w-1 rounded-full", style.stripe)} />
          <h3 id={headingId} className="font-display text-base font-semibold whitespace-nowrap">
            <span className={style.text}>{OUTCOME_LABEL[outcome]}</span>
            <span className="font-medium text-text-secondary"> · {TEAM_SIDE_LABEL[team.team_id]}</span>
          </h3>
          <span className="hidden text-xs text-text-muted tabular-nums sm:inline">
            {formatCompact(team.gold)} gold
          </span>
        </div>
        <TeamObjectives objectives={team.objectives} className="@3xl:ml-auto" />
      </header>
      <TeamTable {...props} players={players} />
      <TeamList {...props} players={players} />
      {team.bans.length > 0 ? (
        <footer className="flex flex-wrap items-center gap-3 border-t border-border px-3 py-2.5 sm:px-4">
          <TeamBans bans={team.bans} />
        </footer>
      ) : null}
    </>
  );

  if (embedded) {
    return (
      <section aria-labelledby={headingId} className="min-w-0 overflow-hidden rounded-xl border border-border bg-surface-2/40">
        {body}
      </section>
    );
  }
  return (
    <GlowCard asChild className="overflow-hidden">
      <section aria-labelledby={headingId}>{body}</section>
    </GlowCard>
  );
}
