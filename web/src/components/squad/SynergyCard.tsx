import { Handshake } from "lucide-react";

import type { SquadPlayer } from "@/api/types";
import { GlowCard } from "@/components/common/GlowCard";
import { SectionHeader } from "@/components/common/SectionHeader";
import { cn } from "@/lib/cn";
import { formatPercent, plural } from "@/lib/format";

import { DetailHeadline, DetailNote, DetailRow, DetailRows, DetailTitle, TwoLine, WinLoss } from "./DetailParts";
import { BinLegend, CellKey, MutedSample, SelfSample } from "./MatrixLegend";
import { gapText, orient, scoreText, type SquadModel } from "./model";
import { FIT_TABLE, PlayerMatrix, type MatrixCellSpec } from "./PlayerMatrix";
import { binColor, synergyBin, SYNERGY_EDGES } from "./scale";

const [E1, E2, E3] = SYNERGY_EDGES;
const TICKS = [`−${E3}`, `−${E2}`, `−${E1}`, `+${E1}`, `+${E2}`, `+${E3}`] as const;

/** Duo synergy: win rate for every pair of friends on the same team, coloured against expectation. */
export function SynergyCard({ model, className }: { model: SquadModel; className?: string }) {
  const { labels, minGames } = model;
  const name = (player: SquadPlayer) => labels.get(player.puuid) ?? player.game_name;

  const cell = (row: SquadPlayer, col: SquadPlayer): MatrixCellSpec => {
    const pair = model.pair(row.puuid, col.puuid);
    if (!pair) {
      return {
        variant: "empty",
        content: <span aria-hidden="true">·</span>,
        label: `${name(row)} and ${name(col)}: no ranked games on the same team`,
      };
    }
    if (pair.games < minGames) {
      return {
        variant: "muted",
        content: <span className="text-xs">{pair.games}</span>,
        label: `${name(row)} with ${name(col)}: ${plural(pair.games, "game")} together, under ${minGames}, too few to rate`,
      };
    }
    return {
      variant: "value",
      fill: binColor(synergyBin(pair.winrate_delta), "win"),
      // The fill encodes the gap from expected, so the gap is also written out: colour is never
      // the only signal, and two equal win rates with different fills explain themselves.
      content: <TwoLine top={formatPercent(pair.winrate)} bottom={`${gapText(pair.winrate_delta)} · ${pair.games}`} />,
      label:
        `${name(row)} with ${name(col)}: ${formatPercent(pair.winrate)} win rate in ${plural(pair.games, "game")}, ` +
        `${gapText(pair.winrate_delta)} points against the expected ${formatPercent(pair.expected_winrate)}`,
    };
  };

  const self = (player: SquadPlayer): MatrixCellSpec => ({
    variant: "self",
    content: <TwoLine top={formatPercent(player.winrate)} bottom={String(player.games)} />,
    label: `${name(player)} overall: ${formatPercent(player.winrate)} win rate in ${plural(player.games, "ranked game")}`,
  });

  const detail = (row: SquadPlayer, col: SquadPlayer) => {
    if (row.puuid === col.puuid) {
      return (
        <>
          <DetailTitle>{name(row)} overall</DetailTitle>
          <DetailHeadline value={formatPercent(row.winrate)}>win rate</DetailHeadline>
          <div className="text-text-secondary tabular-nums">
            {plural(row.games, "ranked game")} · <WinLoss wins={row.wins} losses={row.games - row.wins} />
          </div>
          <DetailRows>
            <DetailRow label="Avg AI Score">{scoreText(row.avg_ai_score)}</DetailRow>
          </DetailRows>
          <DetailNote>The row shows how that win rate moves with each friend.</DetailNote>
        </>
      );
    }
    const pair = model.pair(row.puuid, col.puuid);
    if (!pair) {
      return (
        <>
          <DetailTitle>
            {name(row)} + {name(col)}
          </DetailTitle>
          <p className="text-text-secondary">No ranked games on the same team with these filters.</p>
        </>
      );
    }
    const view = orient(pair, row, col);
    return (
      <>
        <DetailTitle>
          {name(row)} + {name(col)}
        </DetailTitle>
        <DetailHeadline value={formatPercent(view.winrate)}>win rate together</DetailHeadline>
        <div className="text-text-secondary tabular-nums">
          {plural(view.games, "game")} · <WinLoss wins={view.wins} losses={view.losses} />
        </div>
        <DetailRows>
          <DetailRow label="Expected">{formatPercent(view.expected)}</DetailRow>
          <DetailRow label="Vs expected">{gapText(view.delta)} pts</DetailRow>
          <DetailRow label={`${name(row)} usually`}>{formatPercent(row.winrate)}</DetailRow>
          <DetailRow label={`${name(col)} usually`}>{formatPercent(col.winrate)}</DetailRow>
          <DetailRow label={`${name(row)} avg AI Score`}>{scoreText(view.rowAi)}</DetailRow>
          <DetailRow label={`${name(col)} avg AI Score`}>{scoreText(view.colAi)}</DetailRow>
        </DetailRows>
        {view.games < minGames ? (
          <DetailNote>Under {minGames} games together: too few to read much into.</DetailNote>
        ) : (
          <DetailNote>Expected is the average of their usual win rates. AI Scores are from the games they shared.</DetailNote>
        )}
      </>
    );
  };

  return (
    <GlowCard className={cn("flex flex-col gap-4 p-4 sm:p-5", className)}>
      <SectionHeader
        className={FIT_TABLE}
        icon={Handshake}
        eyebrow="Same team"
        title="Duo synergy"
        description="Win rate when two friends queued on the same team, against what their usual win rates predict."
      />
      <div className={cn("flex flex-wrap items-end gap-x-6 gap-y-3", FIT_TABLE)}>
        <BinLegend
          title="Win rate together vs expected (points)"
          arm="win"
          ticks={TICKS}
          lowLabel="Worse together"
          highLabel="Better together"
        />
        <div className="flex flex-col gap-1.5">
          <CellKey sample={<SelfSample>51%</SelfSample>}>Own win rate (diagonal)</CellKey>
          <CellKey sample={<MutedSample>3</MutedSample>}>Under {minGames} games: count only</CellKey>
        </div>
      </div>
      <PlayerMatrix
        players={model.players}
        labels={labels}
        caption="Duo synergy: win rate together, points above or below the expected win rate, and games played for each pair of friends. Rows and columns are players; the diagonal is each player's own win rate."
        cell={cell}
        self={self}
        detail={detail}
      />
      <p className={cn("text-xs leading-relaxed text-text-muted", FIT_TABLE)}>
        Each cell shows the win rate together and, below it, the points above or below expected and the games played
        (&ldquo;+4 · 36&rdquo;); the colour follows the points. Expected is the average of the two players&apos; usual
        win rates. Hover or tap a cell for the record and both players&apos; average AI Score in those games.
      </p>
    </GlowCard>
  );
}
