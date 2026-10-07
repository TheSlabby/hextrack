import { useId, useState } from "react";
import { Link } from "@tanstack/react-router";
import { ChevronDown, Swords } from "lucide-react";

import type { ChampionStat } from "@/api/types";
import { AiScoreBadge, ChampionIcon, EmptyState, GlowCard, SectionHeader, WinRateBar } from "@/components/common";
import { cn } from "@/lib/cn";
import { formatDecimal, formatPercent, plural } from "@/lib/format";
import { ChampionLink } from "@/components/common/ChampionLink";
import { championDisplayName, championSlug } from "@/lib/champions";

import { ChampionInsight } from "./ChampionInsight";

export interface ChampionsCardProps {
  champions: readonly ChampionStat[];
  /** The profile's player when they're on the roster: rows expand into champion insights. */
  puuid?: string | null;
  className?: string;
}

const GRID = "grid grid-cols-[32px_minmax(0,1fr)_52px_38px_48px] items-center gap-x-3";
/**
 * With the expand button: a 24px column, paid for by narrower stat columns and gaps, so the name keeps the
 * same room as without it (the card is only 340px wide in the lg sidebar).
 */
const GRID_EXPAND = "grid grid-cols-[32px_minmax(0,1fr)_44px_34px_44px_24px] items-center gap-x-2";

/** Most played champions this season: games, win rate bar, KDA and average AI Score. */
export function ChampionsCard({ champions, puuid = null, className }: ChampionsCardProps) {
  const grid = puuid ? GRID_EXPAND : GRID;
  return (
    <GlowCard className={cn("flex flex-col gap-3 p-4 sm:p-5", className)}>
      <SectionHeader
        title="Champions"
        eyebrow="Most played · ranked"
        description={puuid ? "Open a champion for your build, recent games and how you compare." : undefined}
        size="sm"
      />
      {champions.length === 0 ? (
        <EmptyState compact icon={Swords} title="No champions yet" description="Play a ranked game to see champion stats." />
      ) : (
        <div role="table" aria-label="Most played champions" className="flex flex-col">
          <div role="row" className={cn(grid, "pb-1.5")}>
            <span role="columnheader">
              <span className="sr-only">Icon</span>
            </span>
            <span role="columnheader" className="label-caps">
              Champion
            </span>
            <span role="columnheader" className="label-caps">
              WR
            </span>
            <span role="columnheader" className="label-caps text-right">
              KDA
            </span>
            <span role="columnheader" className="label-caps text-right">
              Hex
            </span>
            {puuid ? (
              <span role="columnheader">
                <span className="sr-only">Details</span>
              </span>
            ) : null}
          </div>
          <div role="rowgroup" className="flex flex-col divide-y divide-border">
            {champions.map((champion) => (
              <ChampionRow key={champion.champion_id} champion={champion} puuid={puuid} grid={grid} />
            ))}
          </div>
        </div>
      )}
    </GlowCard>
  );
}

function ChampionRow({ champion, puuid, grid }: { champion: ChampionStat; puuid: string | null; grid: string }) {
  const name = championDisplayName(champion.champion_name);
  const losses = champion.games - champion.wins;
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const expandable = Boolean(puuid);
  return (
    <div className="flex flex-col">
      <div
        role="row"
        className={cn(grid, "py-2", expandable && "cursor-pointer")}
        onClick={
          expandable
            ? (event) => {
                // Links (champion page) and the toggle itself handle their own clicks.
                if ((event.target as HTMLElement).closest("a, button")) return;
                if (window.getSelection()?.toString()) return;
                setOpen((value) => !value);
              }
            : undefined
        }
      >
        <span role="cell">
          {/* The name is the accessible link; the portrait is a mouse shortcut to the same page. */}
          <Link
            to="/champions/$champion"
            params={{ champion: championSlug(champion.champion_name) }}
            tabIndex={-1}
            aria-hidden="true"
            className="block rounded-md"
          >
            <ChampionIcon champion={champion.champion_name} size="sm" />
          </Link>
        </span>
        <span role="cell" className="flex min-w-0 flex-col">
          <ChampionLink champion={champion.champion_name} className="max-w-full self-start truncate text-sm font-medium text-text">
            {name}
          </ChampionLink>
          <span className="text-[11px] text-text-muted tabular-nums">{plural(champion.games, "game")}</span>
        </span>
        <span role="cell" className="flex flex-col gap-1">
          <span
            className={cn(
              "text-xs font-semibold tabular-nums",
              champion.winrate >= 0.5 ? "text-text" : "text-text-secondary",
            )}
          >
            {formatPercent(champion.winrate)}
          </span>
          <WinRateBar wins={champion.wins} losses={losses} showLabels={false} size="sm" className="[&>div]:h-1" />
        </span>
        <span
          role="cell"
          className={cn(
            "text-right text-xs font-semibold tabular-nums",
            champion.kda >= 4 ? "text-gold-bright" : champion.kda >= 2.5 ? "text-text" : "text-text-secondary",
          )}
        >
          {formatDecimal(champion.kda, 2)}
        </span>
        <span role="cell" className="flex justify-end">
          <AiScoreBadge score={champion.avg_ai_score} kind="average" size="sm" />
        </span>
        {expandable ? (
          <span role="cell" className="flex justify-end">
            <button
              type="button"
              aria-expanded={open}
              aria-controls={panelId}
              aria-label={`${open ? "Hide" : "Show"} ${name} insights`}
              onClick={() => setOpen((value) => !value)}
              className="-my-1 flex size-6 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-white/5 hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold"
            >
              <ChevronDown className={cn("size-4 transition-transform duration-200", open && "rotate-180")} aria-hidden="true" />
            </button>
          </span>
        ) : null}
      </div>
      {expandable && open && puuid ? (
        <div id={panelId} role="row" className="pb-3">
          <div role="cell" className="rounded-xl border border-border bg-white/[0.02] p-3">
            <ChampionInsight champion={champion.champion_name} puuid={puuid} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
