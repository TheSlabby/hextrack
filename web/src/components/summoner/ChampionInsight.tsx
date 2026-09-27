import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ArrowRight, Crown } from "lucide-react";

import { useChampion, useChampionPlayer } from "@/api/queries";
import type { ChampionPlayer, ChampionPlayerGame, ChampionRole, Position } from "@/api/types";
import { AiScoreBadge } from "@/components/common/AiScoreBadge";
import { DdragonPatch } from "@/components/common/DdragonPatch";
import { ErrorState } from "@/components/common/ErrorState";
import { GameImage } from "@/components/common/GameImage";
import { SpellIcons } from "@/components/common/SpellIcons";
import { ItemPath } from "@/components/champions/BuildPathRow";
import { ChampionTierBadge } from "@/components/champions/ChampionTierBadge";
import { ShareChampionButton } from "@/components/champions/ShareChampionButton";
import { playerSearchValue } from "@/components/match/focus";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { championDisplayName, championSlug } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatCompact, formatDecimal, formatPercent, plural } from "@/lib/format";
import { useRuneTrees } from "@/lib/runes";
import { POSITION_LABELS } from "@/lib/positions";

const ROLES: readonly Position[] = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"];

function asRole(position: Position): ChampionRole | null {
  return ROLES.includes(position) ? (position as ChampionRole) : null;
}

/** "+3.8", "−0.10": the player's number minus everyone's, coloured by which is better. */
function Delta({ value, digits, suffix = "" }: { value: number; digits: number; suffix?: string }) {
  const rounded = Number(value.toFixed(digits));
  const text = `${rounded > 0 ? "+" : rounded < 0 ? "−" : "±"}${Math.abs(rounded).toFixed(digits)}${suffix}`;
  return (
    <span
      className={cn(
        "w-12 text-right text-[11px] font-semibold tabular-nums",
        rounded > 0 ? "text-win" : rounded < 0 ? "text-loss" : "text-text-muted",
      )}
    >
      {text}
    </span>
  );
}

/** One "you vs everyone" line: label, the player's value, everyone's value and the gap. */
function CompareRow({
  label,
  you,
  field,
  format,
  deltaDigits,
  deltaScale = 1,
  deltaSuffix,
}: {
  label: string;
  you: number;
  field: number | null;
  format: (value: number) => string;
  deltaDigits: number;
  deltaScale?: number;
  deltaSuffix?: string;
}) {
  return (
    <div className="flex items-baseline gap-2 text-xs tabular-nums">
      <span className="w-14 shrink-0 text-text-muted">{label}</span>
      <span className="font-semibold text-text">{format(you)}</span>
      <span className="min-w-0 flex-1 truncate text-text-muted">{field === null ? "" : `vs ${format(field)}`}</span>
      {field === null ? null : <Delta value={(you - field) * deltaScale} digits={deltaDigits} suffix={deltaSuffix} />}
    </div>
  );
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="label-caps">{label}</span>
      {children}
    </div>
  );
}

/** W/L chips for the latest games (newest first), each linking to the match. */
function RecentGames({ games, player }: { games: readonly ChampionPlayerGame[]; player: ChampionPlayer }) {
  return (
    <div className="flex flex-wrap gap-1">
      {games.map((game) => (
        <Link
          key={game.match_id}
          to="/match/$matchId"
          params={{ matchId: game.match_id }}
          search={{ player: playerSearchValue(player) }}
          title={`${game.win ? "Win" : "Loss"} · ${game.kills}/${game.deaths}/${game.assists}`}
          aria-label={`${game.win ? "Win" : "Loss"}, ${game.kills} ${game.deaths} ${game.assists}`}
          className={cn(
            "flex h-6 min-w-9 items-center justify-center rounded-md px-1.5 text-[10px] font-semibold tabular-nums transition-colors",
            "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
            game.win ? "bg-win/15 text-win hover:bg-win/25" : "bg-loss/15 text-loss hover:bg-loss/25",
          )}
        >
          {game.kills}/{game.deaths}/{game.assists}
        </Link>
      ))}
    </div>
  );
}

function RunesLine({ player, patch }: { player: ChampionPlayer; patch: string | null }) {
  const trees = useRuneTrees(patch);
  const page = player.rune_page;
  if (!page) return null;
  const keystone = trees.info(page.rune_ids[0]);
  const secondary = trees.info(page.secondary_style_id);
  return (
    <span className="flex items-center gap-1.5" title={keystone?.name}>
      {keystone ? <GameImage src={keystone.icon} alt={keystone.name} className="size-6 rounded-full bg-black/40" /> : null}
      {secondary ? <GameImage src={secondary.icon} alt={secondary.name} className="size-4" /> : null}
      <span className="text-[11px] text-text-muted tabular-nums">{formatPercent(page.pick_rate)}</span>
    </span>
  );
}

function InsightSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading champion insights">
      {Array.from({ length: 4 }, (_, i) => (
        <Skeleton key={i} className="h-4 w-full" />
      ))}
      <Skeleton className="h-7 w-40" />
    </div>
  );
}

/**
 * The expanded part of a profile champion row: how the player does on the champion next to
 * everyone in their main role (this season), their usual core / runes / spells next to the
 * most common core, recent games, best game, squad rank, the champion's tier and actions.
 */
export function ChampionInsight({ champion, puuid }: { champion: string; puuid: string }) {
  const query = useChampionPlayer(champion, puuid, "all");
  const player = query.data;
  const role = player ? asRole(player.main_position) : null;
  // Everyone's most common core and the tier, for the player's main role in recent patches.
  const detail = useChampion(champion, { patch: "recent", role }).data;
  const name = championDisplayName(champion);

  if (query.isPending) return <InsightSkeleton />;
  if (!player) {
    return <ErrorState compact error={query.error} title="Couldn't load these insights" onRetry={() => void query.refetch()} />;
  }
  if (player.games === 0) {
    return <p className="text-xs text-text-muted">No ranked games on {name} this season in Solo/Duo or Flex.</p>;
  }

  const patch = player.recent[0]?.patch ?? null;
  const tier = role ? detail?.roles.find((r) => r.position === role)?.tier ?? null : null;
  const commonCore = detail?.role === role ? detail?.detail?.builds.core[0] : undefined;
  const best = player.best_game;
  const roleLabel = role ? POSITION_LABELS[role] : null;

  return (
    <DdragonPatch patch={patch}>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
          {role && tier ? <ChampionTierBadge tier={tier} role={role} size="sm" focusable /> : null}
          {player.squad_rank ? (
            <span className="inline-flex items-center gap-1 text-text-secondary">
              {player.squad_rank === 1 ? <Crown className="size-3.5 text-gold" aria-hidden="true" /> : null}
              {player.squad_rank === 1
                ? `Top ${name} in the squad`
                : `#${player.squad_rank} of ${player.squad_players} in the squad`}
            </span>
          ) : null}
          {roleLabel ? <span className="text-text-muted">Mostly {roleLabel}</span> : null}
        </div>

        <Section label={roleLabel ? `You vs all ${name} ${roleLabel}` : "This season"}>
          <CompareRow
            label="Win rate"
            you={player.win_rate ?? 0}
            field={player.field_win_rate}
            format={(v) => formatPercent(v, 1)}
            deltaDigits={1}
            deltaScale={100}
          />
          <CompareRow label="KDA" you={player.kda} field={player.field_kda} format={(v) => formatDecimal(v, 2)} deltaDigits={2} />
          <CompareRow
            label="CS/min"
            you={player.cs_per_min}
            field={player.field_cs_per_min}
            format={(v) => formatDecimal(v, 1)}
            deltaDigits={1}
          />
          <CompareRow
            label="Damage"
            you={player.avg_damage}
            field={player.field_avg_damage}
            format={(v) => formatCompact(Math.round(v))}
            deltaDigits={1}
            deltaScale={0.001}
            deltaSuffix="k"
          />
        </Section>

        <Section label="Your build">
          {player.core ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <ItemPath items={player.core.items} size={24} />
              <span className="text-[11px] text-text-muted tabular-nums">
                {formatPercent(player.core.pick_rate)} of {plural(player.timeline_games, "game")}
              </span>
            </div>
          ) : (
            <span className="text-[11px] text-text-muted">
              {player.timeline_games > 0 ? "No finished core yet." : "Item order is still coming in for these games."}
            </span>
          )}
          {commonCore && player.core && commonCore.items.join("-") !== player.core.items.join("-") ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <ItemPath items={commonCore.items} size={20} className="opacity-80" />
              <span className="text-[11px] text-text-muted">most players</span>
            </div>
          ) : commonCore && player.core ? (
            <span className="text-[11px] text-text-muted">Same core as most {name} players.</span>
          ) : null}
          <div className="flex items-center gap-3">
            <RunesLine player={player} patch={patch} />
            {player.spells ? (
              <SpellIcons
                spell1={player.spells.spell_ids[0] ?? 0}
                spell2={player.spells.spell_ids[1] ?? 0}
                orientation="horizontal"
                size="sm"
              />
            ) : null}
          </div>
        </Section>

        <Section label="Recent">
          <RecentGames games={player.recent} player={player} />
          {best ? (
            <Link
              to="/match/$matchId"
              params={{ matchId: best.match_id }}
              search={{ player: playerSearchValue(player) }}
              className="group inline-flex items-center gap-2 self-start rounded-sm text-xs text-text-secondary hover:text-gold-bright focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold"
            >
              <span className="text-text-muted">Best game</span>
              <span className="font-semibold tabular-nums">
                {best.kills}/{best.deaths}/{best.assists}
              </span>
              <AiScoreBadge score={best.ai_score} size="sm" tooltip={false} />
              <ArrowRight className="size-3 opacity-60 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
            </Link>
          ) : null}
        </Section>

        <div className="flex flex-wrap items-center gap-2">
          <Button asChild variant="outline" size="xs">
            <Link to="/champions/$champion" params={{ champion: championSlug(champion) }} search={role ? { role } : {}}>
              {name} builds
              <ArrowRight aria-hidden="true" />
            </Link>
          </Button>
          <ShareChampionButton champion={champion} puuid={puuid} variant="button" />
        </div>
      </div>
    </DdragonPatch>
  );
}
