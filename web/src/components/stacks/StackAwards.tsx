/**
 * Stack awards: the API's verdict awards (carry king, ran it down, tried their best) plus two
 * superlatives derived from the player numbers. Teammates in a stack share the result, so the
 * carry / "ran it down" banter is fair here (web/DESIGN.md → AI Score copy). Averages stay
 * plain numbers: the "Stack MVP" shows its average AI Score ungraded.
 */
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { Crown, HeartCrack, Skull, Sparkles, TrendingDown, Trophy } from "lucide-react";

import type { StackAward, StackPlayer, StackSummary } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { GlowCard } from "@/components/common/GlowCard";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { SectionHeader } from "@/components/common/SectionHeader";
import { cn } from "@/lib/cn";
import { formatDecimal, plural } from "@/lib/format";
import { formatRiotId, summonerParams } from "@/lib/riotId";

import { playerLookup, type PlayerLookup } from "./model";

/** Derived superlatives need this many games (or scored games) per player... */
const SUPERLATIVE_MIN_GAMES = 3;
/**
 * Stack MVP ranks players on an average, so it follows the leaderboard's rule (computeStandings
 * in components/leaderboard/sorting.ts): a minimum sample (up to 20 games) and shrinkage towards
 * 50 with a 20-game prior, so six lucky games can't beat a season. Death magnet uses the same floor.
 */
const RANKED_MIN_GAMES = 20;
const PRIOR_GAMES = 20;
const PRIOR_MEAN = 0.5;

function minGamesFor(counts: readonly number[]): number {
  return Math.max(SUPERLATIVE_MIN_GAMES, Math.min(RANKED_MIN_GAMES, Math.max(0, ...counts)));
}

function shrunkScore(p: StackPlayer): number {
  return ((p.avg_ai_score ?? PRIOR_MEAN) * p.scored_games + PRIOR_MEAN * PRIOR_GAMES) / (p.scored_games + PRIOR_GAMES);
}
/** ...and at least this many qualifying players, or there is nobody to beat. */
const SUPERLATIVE_MIN_PLAYERS = 2;

type Tone = "praise" | "roast" | "ai";

const TONE: Record<Tone, { panel: string; medallion: string; title: string; figure: string }> = {
  praise: {
    panel: "border-gold/20",
    medallion: "border-gold/30 bg-gold/10 text-gold",
    title: "text-gold",
    figure: "text-gold-bright",
  },
  roast: {
    panel: "border-loss/20",
    medallion: "border-loss/30 bg-loss/10 text-loss",
    title: "text-loss",
    figure: "text-loss",
  },
  ai: {
    panel: "border-cyan/20",
    medallion: "border-cyan/25 bg-cyan/8 text-cyan",
    title: "text-cyan",
    figure: "text-text",
  },
};

interface AwardItem {
  id: string;
  title: string;
  icon: LucideIcon;
  tone: Tone;
  puuid: string;
  /** What they did, e.g. "Carried 7 times". */
  feat: ReactNode;
  quip: string;
}

const VERDICT_AWARDS: Record<
  StackAward["key"],
  { title: string; icon: LucideIcon; tone: Tone; feat: (count: number) => string; quip: string }
> = {
  carry_king: {
    title: "Carry King",
    icon: Crown,
    tone: "praise",
    feat: (n) => `Carried ${plural(n, "time")}`,
    quip: "Had the whole stack on their back.",
  },
  tried_their_best: {
    title: "Tried their best",
    icon: HeartCrack,
    tone: "praise",
    feat: (n) => `Stood out in ${plural(n, "loss", "losses")}`,
    quip: "Did everything they could. It wasn't enough.",
  },
  ran_it_down: {
    title: "Ran it down the most",
    icon: TrendingDown,
    tone: "roast",
    feat: (n) => `Ran it down ${plural(n, "time")}`,
    quip: "Owes the stack an apology.",
  },
};

/** Praise first, roasts last. */
const AWARD_ORDER: readonly StackAward["key"][] = ["carry_king", "tried_their_best", "ran_it_down"];

/** Player with the highest `value` among those that qualify; ties go to the most games (list order). */
function topBy(players: readonly StackPlayer[], qualifies: (p: StackPlayer) => boolean, value: (p: StackPlayer) => number) {
  const eligible = players.filter(qualifies);
  if (eligible.length < SUPERLATIVE_MIN_PLAYERS) return null;
  return eligible.reduce((best, p) => (value(p) > value(best) ? p : best));
}

function buildAwards(data: StackSummary): AwardItem[] {
  const items: AwardItem[] = [];
  const byKey = new Map(data.awards.map((award) => [award.key, award]));

  for (const key of AWARD_ORDER) {
    const award = byKey.get(key);
    if (!award || award.count <= 0) continue;
    const meta = VERDICT_AWARDS[key];
    items.push({
      id: key,
      title: meta.title,
      icon: meta.icon,
      tone: meta.tone,
      puuid: award.puuid,
      feat: meta.feat(award.count),
      quip: meta.quip,
    });
  }

  const mvpMin = minGamesFor(data.players.map((p) => p.scored_games));
  const mvp = topBy(
    data.players,
    (p) => p.avg_ai_score !== null && p.scored_games >= mvpMin,
    shrunkScore,
  );
  if (mvp) {
    items.splice(1, 0, {
      id: "stack_mvp",
      title: "Stack MVP",
      icon: Sparkles,
      tone: "ai",
      puuid: mvp.puuid,
      feat: (
        <span className="inline-flex flex-wrap items-center gap-1.5">
          <AiScoreBadge
            score={mvp.avg_ai_score}
            kind="average"
            size="sm"
            detail={`Over ${plural(mvp.scored_games, "scored stack game")}.`}
          />
          <span>average over {plural(mvp.scored_games, "scored game")}</span>
        </span>
      ),
      quip: `Highest average AI Score in the stack (${mvpMin}+ scored games, small samples pulled towards 50).`,
    });
  }

  const deathMin = minGamesFor(data.players.map((p) => p.games));
  const deathMagnet = topBy(
    data.players,
    (p) => p.games >= deathMin && p.deaths > 0,
    (p) => p.deaths / p.games,
  );
  if (deathMagnet) {
    items.push({
      id: "death_magnet",
      title: "Death magnet",
      icon: Skull,
      tone: "roast",
      puuid: deathMagnet.puuid,
      feat: `${formatDecimal(deathMagnet.deaths / deathMagnet.games)} deaths a game over ${plural(deathMagnet.games, "stack")}`,
      quip: "Knows every death recap by heart.",
    });
  }

  return items;
}

function AwardPlayer({ lookup, puuid }: { lookup: PlayerLookup; puuid: string }) {
  const player = lookup.get(puuid);
  if (!player) return <span className="truncate text-sm font-semibold text-text-secondary">Unknown player</span>;
  return (
    <Link
      to="/summoner/$region/$riotId"
      params={summonerParams(player.game_name, player.tag_line)}
      title={formatRiotId(player.game_name, player.tag_line)}
      className="focus-ring max-w-full truncate rounded-sm text-sm font-semibold text-text transition-colors hover:text-gold-bright"
    >
      {player.game_name}
    </Link>
  );
}

function AwardPanel({ item, lookup }: { item: AwardItem; lookup: PlayerLookup }) {
  const tone = TONE[item.tone];
  const Icon = item.icon;
  const player = lookup.get(item.puuid);
  return (
    <li className={cn("flex min-w-0 flex-col gap-2.5 rounded-xl border bg-surface-2/60 p-3", tone.panel)}>
      <div className="flex items-center gap-2">
        <span className={cn("flex size-7 shrink-0 items-center justify-center rounded-lg border", tone.medallion)}>
          <Icon className="size-4" aria-hidden="true" />
        </span>
        <h3 className={cn("truncate text-sm font-semibold", tone.title)}>{item.title}</h3>
      </div>
      <div className="flex min-w-0 items-center gap-3">
        <ProfileIcon iconId={player?.profile_icon_id} size="md" alt="" />
        <div className="flex min-w-0 flex-col gap-0.5">
          <AwardPlayer lookup={lookup} puuid={item.puuid} />
          <span className="text-xs text-text-secondary tabular-nums">{item.feat}</span>
        </div>
      </div>
      <p className="text-xs leading-snug text-text-muted">{item.quip}</p>
    </li>
  );
}

export function StackAwards({ data }: { data: StackSummary }) {
  const items = buildAwards(data);
  if (items.length === 0) return null;
  const lookup = playerLookup(data);

  const description =
    data.verdict_games > 0
      ? `From ${plural(data.verdict_games, "scored stack game")}. Everyone shares the result, so their AI Scores compare.`
      : "Carry awards appear once stack games are scored by the AI model.";

  return (
    <GlowCard className="flex flex-col gap-4 p-4 sm:p-5">
      <SectionHeader size="sm" icon={Trophy} eyebrow="Bragging rights" title="Stack awards" description={description} />
      <ul className="grid gap-3 sm:grid-cols-2">
        {items.map((item) => (
          <AwardPanel key={item.id} item={item} lookup={lookup} />
        ))}
      </ul>
    </GlowCard>
  );
}
