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
  const secondary = runes.info(page.secondary_style_id);
  const name = keystone ? `${keystone.name}${secondary ? ` + ${secondary.name}` : ""}` : `Rune page ${index + 1}`;
  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={`${name}: ${pct(page.win_rate)} win rate, ${pct(page.pick_rate)} pick rate, ${page.games} games`}
      onClick={onSelect}
      title={name}
      className={cn(
        "@container flex min-w-0 rounded-lg border px-2 py-1.5 transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
        selected
          ? "border-gold/45 bg-gold/[0.07]"
          : "border-border bg-white/[0.025] hover:border-border-strong hover:bg-surface-2",
      )}
    >
      <span className="flex w-full flex-col items-center gap-1 @[9rem]:flex-row @[9rem]:gap-2" aria-hidden="true">
        <span className="flex shrink-0 items-end gap-0.5">
          {keystone ? (
            <GameImage src={keystone.icon} alt="" className="size-7 rounded-full bg-black/40 object-contain" />
          ) : (
            <span className="shimmer block size-7 rounded-full" />
          )}
          {secondary ? (
            <GameImage src={secondary.icon} alt="" className="size-3.5 object-contain" />
          ) : (
            <span className="shimmer block size-3.5 rounded-full" />
          )}
        </span>
        <span className="flex min-w-0 flex-col items-center text-[11px] leading-tight tabular-nums @[9rem]:items-start">
          <span className={cn("text-sm font-semibold", winRateTone(page.win_rate))}>{pct(page.win_rate)}</span>
          <span className="text-text-muted">
            {pct(page.pick_rate)} · {formatCompact(page.games)}
          </span>
        </span>
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
      title="Runes"
      icon={Gem}
      description="Pick one of the most common pages (win rate, pick rate · games)."
    >
      {page ? (
        <div className="flex flex-col gap-3">
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
            <p className="text-[11px] leading-relaxed text-text-muted">
              Small numbers: how often each rune is taken on any page. Lit shards are the most common set (
              {pct(topShards.pick_rate)} of games, {pct(topShards.win_rate)} win rate).
            </p>
          ) : null}
        </div>
      ) : (
        <EmptyNote>No rune pages recorded for these games yet.</EmptyNote>
      )}
    </DetailCard>
  );
}
