import { useState } from "react";
import { Gem } from "lucide-react";

import type { ChampionRunes, RunePageOption } from "@/api/types";
import { GameImage } from "@/components/common/GameImage";
import { cn } from "@/lib/cn";
import { formatCompact } from "@/lib/format";
import { useRuneTrees } from "@/lib/runes";
import { statShard } from "@/lib/statShards";

import { DetailCard, EmptyNote } from "./DetailCard";
import { pct, winRateTone } from "./detailModel";
import { RunePage } from "./RunePage";

const PAGE_OPTIONS = 3;

/** A selectable rune page: keystone + secondary tree icons, win and pick rate. */
function PageOption({
  page,
  index,
  selected,
  onSelect,
  patch,
}: {
  page: RunePageOption;
  index: number;
  selected: boolean;
  onSelect: () => void;
  patch: string | null;
}) {
  const runes = useRuneTrees(patch);
  const keystone = runes.info(page.rune_ids[0]);
  const primary = runes.info(page.primary_style_id);
  const secondary = runes.info(page.secondary_style_id);
  const name = keystone ? `${keystone.name}${secondary ? ` + ${secondary.name}` : ""}` : `Rune page ${index + 1}`;
  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={`${name}: ${pct(page.win_rate)} win rate, ${pct(page.pick_rate)} pick rate, ${page.games} games`}
      onClick={onSelect}
      className={cn(
        "flex min-w-0 flex-col items-center gap-1.5 rounded-xl border px-2 py-2.5 text-center transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
        selected
          ? "border-gold/45 bg-gold/[0.07]"
          : "border-border bg-surface-2/40 hover:border-border-strong hover:bg-surface-2",
      )}
    >
      <span className="flex items-end gap-1" aria-hidden="true">
        {keystone ? (
          <GameImage src={keystone.icon} alt="" className="size-8 rounded-full bg-black/40 object-contain" />
        ) : (
          <span className="shimmer block size-8 rounded-full" />
        )}
        {secondary ? (
          <GameImage src={secondary.icon} alt="" className="size-4 object-contain" />
        ) : (
          <span className="shimmer block size-4 rounded-full" />
        )}
      </span>
      <span className="hidden max-w-full truncate text-xs font-medium text-text sm:block" aria-hidden="true">
        {keystone?.name ?? primary?.name ?? " "}
      </span>
      <span className="flex flex-col text-[11px] leading-tight tabular-nums" aria-hidden="true">
        <span className={cn("text-sm font-semibold", winRateTone(page.win_rate))}>{pct(page.win_rate)}</span>
        <span className="text-text-secondary">{pct(page.pick_rate)} pick</span>
        <span className="text-text-muted">{formatCompact(page.games)} games</span>
      </span>
    </button>
  );
}

/** Rune pages: the top pages to pick from, then the chosen page drawn in full. */
export function RuneBuild({ runes, patch }: { runes: ChampionRunes; patch: string | null }) {
  const [selected, setSelected] = useState(0);
  const options = runes.pages.slice(0, PAGE_OPTIONS);
  const page = options[Math.min(selected, options.length - 1)];
  const trees = useRuneTrees(patch);
  const topShards = runes.shards[0];

  return (
    <DetailCard
      eyebrow="Build"
      title="Runes"
      icon={Gem}
      description="The most common full pages. Small numbers: how often each rune is taken on any page."
    >
      {page ? (
        <div className="flex flex-col gap-4">
          {options.length > 1 ? (
            <div className="grid grid-cols-3 gap-2" role="group" aria-label="Rune pages">
              {options.map((option, i) => (
                <PageOption
                  key={option.rune_ids.join("-")}
                  page={option}
                  index={i}
                  selected={option === page}
                  onSelect={() => setSelected(i)}
                  patch={patch}
                />
              ))}
            </div>
          ) : (
            <p className="text-sm text-text-secondary tabular-nums">
              <span className={cn("font-semibold", winRateTone(page.win_rate))}>{pct(page.win_rate)}</span> win rate ·{" "}
              {pct(page.pick_rate)} pick rate · {formatCompact(page.games)} games
            </p>
          )}
          <p className="sr-only">
            Selected page: {page.rune_ids.map((id) => trees.info(id)?.name ?? `rune ${id}`).join(", ")}.
            {topShards ? ` Most common shards: ${topShards.shard_ids.map((id) => statShard(id).name).join(", ")}.` : ""}
          </p>
          <RunePage page={page} picks={runes.picks} shards={runes.shards} shardPicks={runes.shard_picks} patch={patch} />
          {topShards ? (
            <p className="text-xs text-text-muted">
              Lit shards are the most common set ({pct(topShards.pick_rate)} of games, {pct(topShards.win_rate)} win rate).
            </p>
          ) : null}
        </div>
      ) : (
        <EmptyNote>No rune pages recorded for these games yet.</EmptyNote>
      )}
    </DetailCard>
  );
}
