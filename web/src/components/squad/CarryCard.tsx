import { Swords } from "lucide-react";

import type { SquadPlayer } from "@/api/types";
import { GlowCard } from "@/components/common/GlowCard";
import { SectionHeader } from "@/components/common/SectionHeader";
import { cn } from "@/lib/cn";
import { formatPercent, plural } from "@/lib/format";

import { DetailHeadline, DetailNote, DetailRow, DetailRows, DetailTitle, TwoLine } from "./DetailParts";
import { BinLegend, CellKey, MutedSample, SelfSample } from "./MatrixLegend";
import { CARRY_MIN_GAMES, gapText, orient, scoreText, type CarryStanding, type SquadModel } from "./model";
import { FIT_TABLE, PlayerMatrix, type MatrixCellSpec } from "./PlayerMatrix";
import { binColor, carryBin, CARRY_EDGES } from "./scale";

const [E1, E2, E3] = CARRY_EDGES;
const TICKS = [`${50 - E3}%`, `${50 - E2}%`, `${50 - E1}%`, `${50 + E1}%`, `${50 + E2}%`, `${50 + E3}%`] as const;

/**
 * Who carries whom: for every pair of friends on the same team, how often the row player had
 * the higher AI Score. Only games where both were scored by the active model count.
 */
export function CarryCard({
  model,
  standings,
  className,
}: {
  model: SquadModel;
  standings: readonly CarryStanding[];
  className?: string;
}) {
  const { labels, minGames } = model;
  const name = (player: SquadPlayer) => labels.get(player.puuid) ?? player.game_name;
  const standingOf = new Map(standings.map((standing) => [standing.player.puuid, standing]));

  const cell = (row: SquadPlayer, col: SquadPlayer): MatrixCellSpec => {
    const pair = model.pair(row.puuid, col.puuid);
    if (!pair || pair.scored_games === 0) {
      return {
        variant: "empty",
        content: <span aria-hidden="true">·</span>,
        label: pair
          ? `${name(row)} and ${name(col)}: no games scored by the current AI model`
          : `${name(row)} and ${name(col)}: no ranked games on the same team`,
      };
    }
    const view = orient(pair, row, col);
    if (view.scored < minGames) {
      return {
        variant: "muted",
        content: <span className="text-xs">{view.scored}</span>,
        label: `${name(row)} against ${name(col)}: ${plural(view.scored, "scored game")} together, under ${minGames}, too few to rate`,
      };
    }
    const share = view.rowShare ?? 0;
    return {
      variant: "value",
      fill: binColor(carryBin(share), "ai"),
      content: <TwoLine top={formatPercent(share)} bottom={String(view.scored)} />,
      label: `${name(row)} had the higher AI Score than ${name(col)} in ${view.rowHigher} of ${plural(view.scored, "shared game")}, ${formatPercent(share)}`,
    };
  };

  const self = (player: SquadPlayer): MatrixCellSpec => {
    const standing = standingOf.get(player.puuid);
    if (!standing || standing.rate === null) {
      return {
        variant: "self",
        content: <span aria-hidden="true">–</span>,
        label: `${name(player)}: no scored duo games`,
      };
    }
    return {
      variant: "self",
      content: <TwoLine top={formatPercent(standing.rate)} bottom={String(standing.scored)} />,
      label: `${name(player)} against every squad teammate: higher AI Score in ${standing.higher} of ${plural(standing.scored, "duo game")}, ${formatPercent(standing.rate)}`,
    };
  };

  const detail = (row: SquadPlayer, col: SquadPlayer) => {
    if (row.puuid === col.puuid) {
      const standing = standingOf.get(row.puuid);
      return (
        <>
          <DetailTitle>{name(row)} against the squad</DetailTitle>
          {standing && standing.rate !== null ? (
            <>
              <DetailHeadline value={formatPercent(standing.rate)}>had the higher score</DetailHeadline>
              <div className="text-text-secondary tabular-nums">
                {standing.higher} of {plural(standing.scored, "duo game")} with {plural(standing.partners, "teammate")}
              </div>
              {standing.avgDiff !== null ? (
                <DetailRows>
                  <DetailRow label="Avg score gap">{gapText(standing.avgDiff)} pts</DetailRow>
                </DetailRows>
              ) : null}
              {!standing.qualified ? (
                <DetailNote>Under {CARRY_MIN_GAMES} scored duo games, so not ranked yet.</DetailNote>
              ) : null}
            </>
          ) : (
            <p className="text-text-secondary">No scored duo games with these filters.</p>
          )}
        </>
      );
    }
    const pair = model.pair(row.puuid, col.puuid);
    if (!pair || pair.scored_games === 0) {
      return (
        <>
          <DetailTitle>
            {name(row)} vs {name(col)}
          </DetailTitle>
          <p className="text-text-secondary">
            {pair
              ? "They shared games, but none were scored by the current AI model."
              : "No ranked games on the same team with these filters."}
          </p>
        </>
      );
    }
    const view = orient(pair, row, col);
    return (
      <>
        <DetailTitle>
          {name(row)} vs {name(col)}
        </DetailTitle>
        <DetailHeadline value={formatPercent(view.rowShare ?? 0)}>{name(row)} scored higher</DetailHeadline>
        <div className="text-text-secondary tabular-nums">
          {view.rowHigher} of {plural(view.scored, "shared game")}
          {view.ties > 0 ? `, ${plural(view.ties, "tie")}` : null}
        </div>
        <DetailRows>
          <DetailRow label={`${name(col)} scored higher`}>{view.colHigher}</DetailRow>
          <DetailRow label={`${name(row)} avg AI Score`}>{scoreText(view.rowAi)}</DetailRow>
          <DetailRow label={`${name(col)} avg AI Score`}>{scoreText(view.colAi)}</DetailRow>
          {view.diff !== null ? <DetailRow label="Avg score gap">{gapText(view.diff)} pts</DetailRow> : null}
        </DetailRows>
        {view.scored < minGames ? (
          <DetailNote>Under {minGames} scored games together: too few to read much into.</DetailNote>
        ) : view.scored < view.games ? (
          <DetailNote>
            {plural(view.games - view.scored, "shared game")} without a score from the current model{" "}
            {view.games - view.scored === 1 ? "is" : "are"} left out.
          </DetailNote>
        ) : null}
      </>
    );
  };

  return (
    <GlowCard glow="cyan" className={cn("flex flex-col gap-4 p-4 sm:p-5", className)}>
      <SectionHeader
        className={FIT_TABLE}
        icon={Swords}
        eyebrow="AI Score head-to-head"
        title="Who carries whom"
        description="Who had the higher AI Score when you queued together."
      />
      <div className={cn("flex flex-wrap items-end gap-x-6 gap-y-3", FIT_TABLE)}>
        <BinLegend
          title="Row player had the higher score in…"
          arm="ai"
          ticks={TICKS}
          lowLabel="Less often"
          highLabel="More often"
        />
        <div className="flex flex-col gap-1.5">
          <CellKey sample={<SelfSample>52%</SelfSample>}>Against the whole squad (diagonal)</CellKey>
          <CellKey sample={<MutedSample>3</MutedSample>}>Under {minGames} scored games: count only</CellKey>
        </div>
      </div>
      <PlayerMatrix
        players={model.players}
        labels={labels}
        caption="Who carries whom: share of shared games in which the row player had the higher AI Score than the column player, with the number of scored games."
        cell={cell}
        self={self}
        detail={detail}
      />
      <p className={cn("text-xs leading-relaxed text-text-muted", FIT_TABLE)}>
        Read across a row: the big number is how often that player's AI Score beat the column player's, the small one
        the scored games they shared. Teammates share the result, so a win or loss doesn't tip it either way, but roles
        do: the score leans on gold and objectives, so a support can trail a carry who played just as well. Only games where both
        were scored by the current AI model count.
      </p>
    </GlowCard>
  );
}
