import { useState, type ReactElement } from "react";
import { CircleHelp, Sparkles } from "lucide-react";

import { useMatchAiExplain } from "@/api/queries";
import type { ParticipantSummary } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { ErrorState } from "@/components/common/ErrorState";
import { InGameRankPill } from "@/components/match/MatchBits";
import { inGameRank } from "@/components/match/matchUtils";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { championDisplayName } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { AI_SCORE_RESULT_NOTE, gradeForRate, toScore100 } from "@/lib/score";

import { AiScoreExplainer } from "./AiScoreExplainer";
import { buildDrivers, type DriverDisplay } from "./insights";

/** Stat families listed before the rest are folded into "Everything else". */
const TOP_DRIVERS = 6;

interface TeamLike {
  team_id: ParticipantSummary["team_id"];
  win: boolean;
  participants: readonly ParticipantSummary[];
}

export interface AiScoreBreakdownButtonProps {
  matchId: string;
  participant: ParticipantSummary;
  teams: readonly TeamLike[];
  remake: boolean;
  layout?: "row" | "stack";
  size?: "sm" | "md";
  className?: string;
}

/**
 * The AI Score pill (plus MVP / ACE / #N) as in `AiScoreWithRank`, but the score opens a
 * "Why this score?" breakdown of which stats moved it. Unscored lines and remakes render the
 * plain pill.
 */
export function AiScoreBreakdownButton({
  matchId,
  participant,
  teams,
  remake,
  layout = "row",
  size = "md",
  className,
}: AiScoreBreakdownButtonProps) {
  const rank = inGameRank(participant, teams, remake);
  const scored = participant.ai_score !== null && !remake;
  const name = participant.game_name ?? championDisplayName(participant.champion_name);

  const badge = <AiScoreBadge score={participant.ai_score} size={size} tooltip={!scored} />;
  return (
    <div className={cn("inline-flex items-center", layout === "stack" ? "flex-col gap-1" : "gap-1.5", className)}>
      {scored ? (
        <AiScoreBreakdownDialog
          matchId={matchId}
          participant={participant}
          trigger={
            <button
              type="button"
              aria-label={`AI Score ${toScore100(participant.ai_score ?? 0)} for ${name}: see why`}
              title="Why this score?"
              className="cursor-pointer rounded-full transition-transform hover:scale-105 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan"
            >
              {badge}
            </button>
          }
        />
      ) : (
        badge
      )}
      {rank ? <InGameRankPill rank={rank} /> : null}
    </div>
  );
}

/** Wraps any trigger (the score pill, the hero ring's "Why?" button) in the breakdown dialog. */
export function AiScoreBreakdownDialog({
  matchId,
  participant,
  trigger,
}: {
  matchId: string;
  participant: ParticipantSummary;
  trigger: ReactElement;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        {open ? <Breakdown matchId={matchId} participant={participant} /> : null}
      </DialogContent>
    </Dialog>
  );
}

/** AI Score points a stat family moved the score by (its share of score − base). */
function points(driver: DriverDisplay, base: number): number {
  return driver.attribution * base * (1 - base) * 100;
}

function signed(value: number): string {
  const rounded = Math.round(value);
  if (rounded === 0) return value >= 0 ? "+0" : "−0";
  return rounded > 0 ? `+${rounded}` : `−${Math.abs(rounded)}`;
}

function Breakdown({ matchId, participant }: { matchId: string; participant: ParticipantSummary }) {
  const query = useMatchAiExplain(matchId, participant.puuid);
  const name = participant.game_name ?? "This player";
  const champion = championDisplayName(participant.champion_name);

  const header = (
    <DialogHeader>
      <DialogTitle className="flex items-center gap-2">
        <Sparkles className="size-4 text-cyan" aria-hidden="true" />
        Why this AI Score?
      </DialogTitle>
      <DialogDescription>
        What moved the model's read of {name}'s stat line as {champion} in this game.
      </DialogDescription>
    </DialogHeader>
  );

  if (query.isPending) {
    return (
      <div className="flex flex-col gap-4">
        {header}
        <div className="flex flex-col gap-2" role="status" aria-label="Working out the breakdown">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-9 rounded-lg" />
          ))}
        </div>
      </div>
    );
  }
  if (!query.data) {
    return (
      <div className="flex flex-col gap-4">
        {header}
        <ErrorState compact error={query.error} title="Couldn't explain this score" onRetry={() => void query.refetch()} />
      </div>
    );
  }

  const data = query.data;
  const base = data.base_score ?? 0.5;
  const drivers = buildDrivers(data.features)
    .map((driver) => ({ driver, pts: points(driver, base) }))
    .sort((a, b) => Math.abs(b.pts) - Math.abs(a.pts));
  const top = drivers.slice(0, TOP_DRIVERS);
  const restPts = drivers.slice(TOP_DRIVERS).reduce((sum, d) => sum + d.pts, 0);
  const maxAbs = Math.max(1, ...top.map((d) => Math.abs(d.pts)), Math.abs(restPts));
  const score = toScore100(data.score);
  const grade = gradeForRate(data.score);

  return (
    <div className="flex flex-col gap-4">
      {header}

      <div className="flex items-center gap-3 rounded-xl border border-border bg-white/[0.02] p-3">
        <ChampionIcon champion={participant.champion_name} size="md" />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-semibold text-text">{name}</span>
          <span className="text-xs text-text-secondary">
            {data.win ? "Victory" : "Defeat"} · {grade.label}
          </span>
        </div>
        <AiScoreBadge score={data.score} size="md" tooltip={false} />
      </div>

      <ol className="flex flex-col gap-1.5" aria-label="How the score was built">
        <Step label="An average stat line scores" value={String(toScore100(base))} muted />
        {top.map(({ driver, pts }) => (
          <DriverRow key={driver.key} driver={driver} pts={pts} maxAbs={maxAbs} />
        ))}
        {drivers.length > TOP_DRIVERS ? (
          <li className="flex items-center gap-3 px-1 text-xs text-text-secondary">
            <span className="min-w-0 flex-1">Everything else ({drivers.length - TOP_DRIVERS} stats)</span>
            <Bar pts={restPts} maxAbs={maxAbs} muted />
            <span className="w-9 text-right font-semibold tabular-nums">{signed(restPts)}</span>
          </li>
        ) : null}
        <Step label="This game's AI Score" value={String(score)} strong />
      </ol>

      <p className="text-xs leading-relaxed text-text-muted">
        Each bar is how far that stat moved the score from an average line; they add up to the final
        score. {AI_SCORE_RESULT_NOTE}
      </p>
      <AiScoreExplainer
        trigger={
          <Button variant="ghost" size="xs" className="-ml-1.5 w-fit text-cyan hover:bg-cyan/10 hover:text-cyan">
            <CircleHelp aria-hidden="true" />
            How the AI Score works
          </Button>
        }
      />
    </div>
  );
}

function Step({ label, value, muted, strong }: { label: string; value: string; muted?: boolean; strong?: boolean }) {
  return (
    <li
      className={cn(
        "flex items-center justify-between rounded-lg px-3 py-2 text-sm",
        strong ? "border border-cyan/30 bg-cyan/10 font-semibold text-text" : "bg-white/[0.03]",
        muted && "text-text-secondary",
      )}
    >
      <span>{label}</span>
      <span className="font-display text-base tabular-nums">{value}</span>
    </li>
  );
}

function DriverRow({ driver, pts, maxAbs }: { driver: DriverDisplay; pts: number; maxAbs: number }) {
  const h = driver.headline;
  const detail = h.avg !== null ? `${h.you} vs ${h.avg} avg${h.unit ? ` ${h.unit}` : ""}` : `${h.you}${h.unit ? ` ${h.unit}` : ""}`;
  const muted = driver.neutral || driver.mixed;
  return (
    <li className="flex items-center gap-3 px-1">
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-sm text-text">
          {driver.label}
          {driver.mixed ? (
            <span
              className="ml-1.5 text-[10px] font-semibold tracking-wide text-text-muted uppercase"
              title="The model weighs this stat against the rest of the line, so its direction here is a side effect"
            >
              mixed
            </span>
          ) : null}
        </span>
        <span className="truncate text-[11px] text-text-muted tabular-nums">{detail}</span>
      </span>
      <Bar pts={pts} maxAbs={maxAbs} muted={muted} />
      <span
        className={cn(
          "w-9 text-right text-sm font-semibold tabular-nums",
          muted ? "text-text-secondary" : pts >= 0 ? "text-score-s" : "text-loss",
        )}
      >
        {signed(pts)}
      </span>
    </li>
  );
}

/** Diverging bar around a centre line: right (teal) lifts the score, left (red) lowers it. */
function Bar({ pts, maxAbs, muted }: { pts: number; maxAbs: number; muted?: boolean }) {
  const width = `${Math.min(50, (Math.abs(pts) / maxAbs) * 50)}%`;
  return (
    <span aria-hidden="true" className="relative h-2 w-24 shrink-0 rounded-full bg-white/[0.05] sm:w-32">
      <span className="absolute inset-y-0 left-1/2 w-px bg-border-strong" />
      <span
        className={cn(
          "absolute inset-y-0 rounded-full",
          muted ? "bg-text-muted/50" : pts >= 0 ? "bg-score-s" : "bg-loss",
          pts >= 0 ? "left-1/2" : "right-1/2",
        )}
        style={{ width }}
      />
    </span>
  );
}
