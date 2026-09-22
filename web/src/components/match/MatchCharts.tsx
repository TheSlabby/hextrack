/**
 * Match-detail charts: per-team damage share (small multiples on a shared scale) and the AI
 * Score ranking of all ten players. Themed through @/lib/chartTheme.
 */
import { useId, useMemo } from "react";
import { useReducedMotion } from "motion/react";
import { Bar, BarChart, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Sparkles } from "lucide-react";

import type { MatchDetail, ParticipantSummary, TeamDetail } from "@/api/types";
import { EmptyState } from "@/components/common/EmptyState";
import { cn } from "@/lib/cn";
import {
  CHART_COLORS,
  CHART_FONT_SIZE,
  ChartTooltip,
  barTooltipProps,
  chartAnimation,
  horizontalBarProps,
  referenceLineProps,
  xAxisProps,
  yAxisProps,
} from "@/lib/chartTheme";
import { useDdragon } from "@/lib/ddragon";
import { formatInteger, formatPercent } from "@/lib/format";
import { gradeForScore, toScore100 } from "@/lib/score";
import { championDisplayName } from "@/lib/champions";

import { displayName, inGameRank, OUTCOME_LABEL, outcomeOf, sortByPosition, TEAM_SIDE_LABEL } from "./matchUtils";

const ROW_HEIGHT = 28;
const TICK_ICON = 16;
const CHAR_WIDTH = 6.1;
/** Recharts' default tick line length; a left y-axis places tick x at width - tickSize - tickMargin. */
const TICK_SIZE = 6;
const TICK_INSET = TICK_SIZE + yAxisProps.tickMargin;

interface TickRow {
  champion: string;
  name: string;
  focused: boolean;
  tracked: boolean;
  /** Optional leading label, e.g. "#1". */
  prefix?: string;
}

interface ChampionTickProps {
  x?: number | string;
  y?: number | string;
  payload?: { value?: unknown };
  rows: ReadonlyMap<string, TickRow>;
  axisWidth: number;
}

/** Category keys are puuids; the tooltip body names the player instead. */
const hideTooltipHeading = () => null;

function truncate(text: string, maxChars: number): string {
  return text.length > maxChars ? `${text.slice(0, Math.max(1, maxChars - 1))}…` : text;
}

/** Y-axis tick: [rank] [champion portrait] [player name], left-aligned in the axis gutter. */
function ChampionTick({ x, y, payload, rows, axisWidth }: ChampionTickProps) {
  const dd = useDdragon();
  const clipId = `tick-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const row = rows.get(String(payload?.value ?? ""));
  if (!row) return null;
  // Left edge of the axis gutter (+2px breathing room); the tick x sits TICK_INSET from its right edge.
  const left = Number(x) - (axisWidth - TICK_INSET) + 2;
  const prefixWidth = row.prefix ? 28 : 0;
  const iconX = left + prefixWidth;
  const nameX = iconX + TICK_ICON + 6;
  const maxChars = Math.max(4, Math.floor((Number(x) - 2 - nameX) / CHAR_WIDTH));
  const nameFill = row.tracked ? CHART_COLORS.goldBright : row.focused ? CHART_COLORS.text : CHART_COLORS.textSecondary;

  return (
    <g transform={`translate(0, ${Number(y)})`}>
      {row.prefix ? (
        <text x={left} y={0} dy="0.35em" fill={CHART_COLORS.axis} fontSize={CHART_FONT_SIZE} fontWeight={600} style={{ fontVariantNumeric: "tabular-nums" }}>
          {row.prefix}
        </text>
      ) : null}
      <clipPath id={clipId}>
        <rect x={iconX} y={-TICK_ICON / 2} width={TICK_ICON} height={TICK_ICON} rx={4} />
      </clipPath>
      <rect x={iconX} y={-TICK_ICON / 2} width={TICK_ICON} height={TICK_ICON} rx={4} fill={CHART_COLORS.axisLine} />
      <image
        href={dd.championIcon(row.champion)}
        x={iconX - 1}
        y={-TICK_ICON / 2 - 1}
        width={TICK_ICON + 2}
        height={TICK_ICON + 2}
        clipPath={`url(#${clipId})`}
        preserveAspectRatio="xMidYMid slice"
      />
      <text
        x={nameX}
        y={0}
        dy="0.35em"
        fill={nameFill}
        fontSize={CHART_FONT_SIZE + 1}
        fontWeight={row.focused ? 650 : 500}
      >
        <title>{`${row.name} · ${championDisplayName(row.champion)}`}</title>
        {truncate(row.name, maxChars)}
      </text>
    </g>
  );
}

function tickRow(p: ParticipantSummary, focusPuuid: string | undefined, prefix?: string): TickRow {
  return {
    champion: p.champion_name,
    name: displayName(p),
    focused: p.puuid === focusPuuid,
    tracked: p.is_tracked,
    prefix,
  };
}

/** Swatch + label legend (mirrors bar marks with a rect). */
function Legend({ items }: { items: ReadonlyArray<{ color: string; label: string }> }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-secondary" aria-label="Legend">
      {items.map((item) => (
        <li key={item.label} className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="size-2.5 rounded-[3px]" style={{ backgroundColor: item.color }} />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

function teamColor(team: Pick<TeamDetail, "win">, remake: boolean): string {
  if (remake) return CHART_COLORS.neutral;
  return team.win ? CHART_COLORS.win : CHART_COLORS.loss;
}

// --- damage share -------------------------------------------------------------------------

interface ShareDatum {
  id: string;
  share: number;
  damage: number;
  name: string;
  champion: string;
}

function niceShareMax(max: number): number {
  const steps = [0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 0.75, 1];
  return steps.find((step) => max <= step) ?? 1;
}

function DamageShareTeam({
  team,
  remake,
  focusPuuid,
  domainMax,
  axisWidth,
}: {
  team: TeamDetail;
  remake: boolean;
  focusPuuid: string | undefined;
  domainMax: number;
  axisWidth: number;
}) {
  const reduced = useReducedMotion();
  const players = sortByPosition(team.participants);
  const total = players.reduce((sum, p) => sum + p.damage_to_champions, 0);
  const data: ShareDatum[] = players.map((p) => ({
    id: p.puuid,
    share: total > 0 ? p.damage_to_champions / total : 0,
    damage: p.damage_to_champions,
    name: displayName(p),
    champion: p.champion_name,
  }));
  const rows = new Map(players.map((p) => [p.puuid, tickRow(p, focusPuuid)]));
  const color = teamColor(team, remake);
  const outcome = outcomeOf(remake, team.win);

  return (
    <figure className="flex min-w-0 flex-col gap-2">
      <figcaption className="flex items-center gap-2 text-xs">
        <span aria-hidden="true" className="size-2.5 rounded-[3px]" style={{ backgroundColor: color }} />
        <span className="font-semibold text-text">{OUTCOME_LABEL[outcome]}</span>
        <span className="text-text-muted">
          {TEAM_SIDE_LABEL[team.team_id]} · {formatInteger(total)} dmg
        </span>
      </figcaption>
      <div style={{ height: data.length * ROW_HEIGHT + 4 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 2, right: 44, bottom: 2, left: 0 }} barCategoryGap={6}>
            <XAxis type="number" dataKey="share" domain={[0, domainMax]} hide />
            <YAxis
              type="category"
              dataKey="id"
              {...yAxisProps}
              width={axisWidth}
              interval={0}
              tick={(props: Omit<ChampionTickProps, "rows" | "axisWidth">) => (
                <ChampionTick {...props} rows={rows} axisWidth={axisWidth} />
              )}
            />
            <Tooltip
              {...barTooltipProps}
              content={
                <ChartTooltip
                  labelFormatter={hideTooltipHeading}
                  renderBody={(datum) => {
                    const d = datum as ShareDatum;
                    return (
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-2">
                          <span aria-hidden="true" className="h-0.5 w-3 rounded-full" style={{ backgroundColor: color }} />
                          <span className="font-display text-sm font-semibold tabular-nums text-text">{formatPercent(d.share)}</span>
                          <span className="text-text-secondary">of team damage</span>
                        </div>
                        <span className="text-text-secondary">
                          <span className="font-medium text-text">{d.name}</span> · {championDisplayName(d.champion)} ·{" "}
                          <span className="tabular-nums">{formatInteger(d.damage)}</span>
                        </span>
                      </div>
                    );
                  }}
                />
              }
            />
            <Bar dataKey="share" {...horizontalBarProps} maxBarSize={16} fill={color} {...chartAnimation(reduced)}>
              <LabelList
                dataKey="share"
                position="right"
                offset={8}
                formatter={(value: unknown) => (typeof value === "number" ? formatPercent(value) : "")}
                style={{ fill: CHART_COLORS.textSecondary, fontSize: CHART_FONT_SIZE, fontVariantNumeric: "tabular-nums", fontWeight: 600 }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

/**
 * Share of each team's damage to champions per player, one panel per team on a shared x
 * scale. Every bar carries its value, so there is no value axis.
 */
export function DamageShareChart({
  match,
  teams = match.teams,
  focusPuuid,
  className,
}: {
  match: MatchDetail;
  /** Display order (defaults to blue side first). */
  teams?: readonly TeamDetail[];
  focusPuuid?: string;
  className?: string;
}) {
  const domainMax = useMemo(() => {
    let max = 0;
    for (const team of match.teams) {
      const total = team.participants.reduce((sum, p) => sum + p.damage_to_champions, 0);
      for (const p of team.participants) max = Math.max(max, total > 0 ? p.damage_to_champions / total : 0);
    }
    return niceShareMax(max);
  }, [match.teams]);

  return (
    <div className={cn("grid gap-5 @2xl:grid-cols-2", className)}>
      {teams.map((team) => (
        <DamageShareTeam
          key={team.team_id}
          team={team}
          remake={match.remake}
          focusPuuid={focusPuuid}
          domainMax={domainMax}
          axisWidth={124}
        />
      ))}
    </div>
  );
}

// --- AI score ranking ---------------------------------------------------------------------

interface RankDatum {
  id: string;
  score: number;
  win: boolean;
  name: string;
  champion: string;
  rankLabel: string | null;
  teamLabel: string;
  color: string;
}

/**
 * All ten players ranked by AI Score (0–100), coloured by team result, with the 50 "coin
 * flip" line for reference. Players without a score are left out and counted below.
 */
export function AiRankingChart({
  match,
  focusPuuid,
  className,
}: {
  match: MatchDetail;
  focusPuuid?: string;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const axisWidth = 150;

  const { data, rows, unscored } = useMemo(() => {
    const scored: ParticipantSummary[] = [];
    let missing = 0;
    for (const team of match.teams) {
      for (const p of team.participants) {
        if (p.ai_score === null) missing += 1;
        else scored.push(p);
      }
    }
    scored.sort((a, b) => (b.ai_score ?? 0) - (a.ai_score ?? 0) || (a.ai_rank ?? 99) - (b.ai_rank ?? 99));
    const teamOf = new Map(match.teams.map((t) => [t.team_id, t]));
    const chartRows = new Map<string, TickRow>();
    const chartData: RankDatum[] = scored.map((p, index) => {
      const team = teamOf.get(p.team_id);
      const rank = inGameRank(p, match.teams, match.remake);
      const position = p.ai_rank ?? index + 1;
      chartRows.set(p.puuid, tickRow(p, focusPuuid, `#${position}`));
      return {
        id: p.puuid,
        score: toScore100(p.ai_score ?? 0),
        win: p.win,
        name: displayName(p),
        champion: p.champion_name,
        rankLabel: rank && rank.kind !== "rank" ? rank.label : null,
        teamLabel: `${OUTCOME_LABEL[outcomeOf(match.remake, team?.win ?? p.win)]} · ${TEAM_SIDE_LABEL[p.team_id]}`,
        color: team ? teamColor(team, match.remake) : CHART_COLORS.neutral,
      };
    });
    return { data: chartData, rows: chartRows, unscored: missing };
  }, [match, focusPuuid]);

  if (data.length === 0) {
    return (
      <EmptyState
        compact
        tone="ai"
        icon={Sparkles}
        title="No AI Scores for this match"
        description={
          match.remake
            ? "Remakes aren't scored."
            : "Scores appear once an AI model is trained and this match has been scored."
        }
        className={cn("flex-1", className)}
      />
    );
  }

  const legend = match.remake
    ? []
    : [...match.teams]
        .sort((a, b) => Number(b.win) - Number(a.win))
        .map((team) => ({
          color: teamColor(team, match.remake),
          label: `${OUTCOME_LABEL[outcomeOf(match.remake, team.win)]} · ${TEAM_SIDE_LABEL[team.team_id]}`,
        }));

  return (
    <div className={cn("flex min-w-0 flex-col gap-3", className)}>
      {legend.length > 0 ? <Legend items={legend} /> : null}
      <div style={{ height: data.length * ROW_HEIGHT + 30 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 36, bottom: 0, left: 0 }} barCategoryGap={6}>
            <XAxis
              type="number"
              dataKey="score"
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
              {...xAxisProps}
              minTickGap={8}
            />
            <YAxis
              type="category"
              dataKey="id"
              {...yAxisProps}
              width={axisWidth}
              interval={0}
              tick={(props: Omit<ChampionTickProps, "rows" | "axisWidth">) => (
                <ChampionTick {...props} rows={rows} axisWidth={axisWidth} />
              )}
            />
            <ReferenceLine x={50} {...referenceLineProps} />
            <Tooltip
              {...barTooltipProps}
              content={
                <ChartTooltip
                  labelFormatter={hideTooltipHeading}
                  renderBody={(datum) => {
                    const d = datum as RankDatum;
                    const grade = gradeForScore(d.score);
                    return (
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-2">
                          <span aria-hidden="true" className="h-0.5 w-3 rounded-full" style={{ backgroundColor: d.color }} />
                          <span className="font-display text-sm font-semibold tabular-nums text-text">{d.score}</span>
                          <span className={cn("font-display font-bold", grade.textClass)}>{grade.grade}</span>
                          <span className="text-text-secondary">{grade.label}</span>
                          {d.rankLabel ? <span className="font-semibold text-gold">{d.rankLabel}</span> : null}
                        </div>
                        <span className="text-text-secondary">
                          <span className="font-medium text-text">{d.name}</span> · {championDisplayName(d.champion)}
                        </span>
                        <span className="text-text-muted">{d.teamLabel}</span>
                      </div>
                    );
                  }}
                />
              }
            />
            {/* minPointSize keeps a score of 0 visible (and labelled) instead of reading as missing data. */}
            <Bar dataKey="score" {...horizontalBarProps} maxBarSize={16} minPointSize={2} {...chartAnimation(reduced)}>
              {data.map((d) => (
                <Cell key={d.id} fill={d.color} />
              ))}
              <LabelList
                dataKey="score"
                position="right"
                offset={8}
                style={{ fill: CHART_COLORS.text, fontSize: CHART_FONT_SIZE, fontVariantNumeric: "tabular-nums", fontWeight: 600 }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-text-muted">
        50 is a coin flip{unscored > 0 ? ` · ${unscored} player${unscored === 1 ? "" : "s"} not scored` : ""}
      </p>
    </div>
  );
}
