import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Check, ImageDown, LoaderCircle } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { championPlayerQuery, championQuery } from "@/api/queries";
import type { LeaderboardQueue } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { canShareFiles, copyWithToast, downloadWithToast, shareWithToast } from "@/components/match/shareActions";
import { canCopyImage } from "@/components/match/shareRecap";
import { championDisplayName } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { useDdragon } from "@/lib/ddragon";
import { runeDataQuery } from "@/lib/runes";

import {
  buildChampionCard,
  championCardArt,
  championCardFilename,
  renderChampionCardPng,
  type ChampionCard,
} from "./shareChampion";

export interface ShareChampionButtonProps {
  /** Data Dragon key of the champion. */
  champion: string;
  /** Roster player whose games on the champion the card shows. */
  puuid: string;
  queue?: LeaderboardQueue;
  /** "icon": a small icon button for list rows; "button": a labelled button. */
  variant?: "icon" | "button";
  className?: string;
}

interface Made {
  card: ChampionCard;
  blob: Blob;
}

/** A rendered card is reused for this long (the data's own stale time). */
const REUSE_MS = 5 * 60_000;

/**
 * Copies a "<Player>'s <Champion> this season" card (PNG) to the clipboard. The data (the
 * player's games on it, and the champion's tier in their main role) is fetched on click.
 */
export function ShareChampionButton({ champion, puuid, queue = "all", variant = "icon", className }: ShareChampionButtonProps) {
  const queryClient = useQueryClient();
  const dd = useDdragon();
  const [status, setStatus] = useState<"idle" | "busy" | "copied">("idle");
  const [support] = useState(() => ({ copy: canCopyImage(), share: canShareFiles() }));
  const made = useRef<{ key: string; at: number; result: Promise<Made> } | null>(null);

  useEffect(() => {
    if (status !== "copied") return;
    const id = window.setTimeout(() => setStatus("idle"), 2_000);
    return () => window.clearTimeout(id);
  }, [status]);

  /** Fetches the data (cached with the pages' own queries), then draws the card. */
  const make = (): Promise<Made> => {
    const key = `${champion.toLowerCase()}:${puuid}:${queue}`;
    const cached = made.current;
    if (cached && cached.key === key && Date.now() - cached.at < REUSE_MS) return cached.result;
    const result = (async (): Promise<Made> => {
      const [player, detail] = await Promise.all([
        queryClient.fetchQuery(championPlayerQuery(champion, puuid, queue)),
        // The tier is a nice-to-have: the card still renders without it.
        queryClient.fetchQuery(championQuery(champion, { patch: "recent", queue })).catch(() => null),
      ]);
      const tier = detail?.roles.find((r) => r.position === player.main_position)?.tier ?? null;
      const card = buildChampionCard(player, tier);
      const art = await championCardArt(player, {
        cdn: dd.cdn,
        latestVersion: dd.latest.version,
        runeCatalog: (version) => queryClient.fetchQuery(runeDataQuery(version, dd.cdn)).then((data) => data.catalog),
      });
      return { card, blob: await renderChampionCardPng(card, art) };
    })();
    made.current = { key, at: Date.now(), result };
    result.catch(() => {
      if (made.current?.result === result) made.current = null;
    });
    return result;
  };

  const name = championDisplayName(champion);
  const action = support.copy ? "copy" : support.share ? "share" : "download";
  const verb = { copy: "Copy", share: "Share", download: "Download" }[action];
  const label = `${verb} ${name} season card`;
  const tooltip =
    action === "copy" ? `Copy a ${name} season card for Discord` : action === "share" ? `Share a ${name} season card` : `Download a ${name} season card`;

  const onClick = (event: MouseEvent) => {
    // Keep the click away from row links and row click handlers around the button.
    event.preventDefault();
    event.stopPropagation();
    // Everything below runs synchronously with the click: Safari drops clipboard writes after an await.
    const result = make();
    let card: ChampionCard | null = null;
    const blob = result.then((r) => {
      card = r.card;
      return r.blob;
    });
    const filename = () => (card ? championCardFilename(card) : "hextrack-champion.png");
    const download = () => void downloadWithToast(blob, filename, "Couldn't create the card");
    setStatus("busy");
    let done: Promise<boolean>;
    if (action === "copy") {
      done = copyWithToast(blob, {
        message: () => `${card?.champion ?? name} card copied. Paste it into Discord.`,
        alt: () => card?.alt ?? label,
        blocked: { description: "Your browser blocked it. Download it instead.", fallback: { label: "Download", run: download } },
      });
    } else if (action === "share") {
      done = shareWithToast(blob, filename, () => card?.title ?? label).then(() => false);
    } else {
      done = downloadWithToast(blob, filename, "Couldn't create the card").then(() => false);
    }
    void done.then((ok) => setStatus(ok ? "copied" : "idle"));
  };
  const warm = () => void make().catch(() => undefined);

  const Icon = status === "busy" ? LoaderCircle : status === "copied" ? Check : ImageDown;
  const icon = (
    <Icon
      aria-hidden="true"
      className={cn(status === "busy" && "animate-spin motion-reduce:animate-none", status === "copied" && "text-score-a")}
    />
  );
  const common = {
    type: "button" as const,
    onClick,
    onPointerEnter: warm,
    onFocus: warm,
    "aria-busy": status === "busy",
  };

  if (variant === "button") {
    return (
      <Button {...common} variant="outline" size="sm" aria-label={`${label}: an image for Discord`} className={className}>
        {icon}
        {status === "copied" ? "Copied" : status === "busy" ? "Making card…" : `${verb} card`}
      </Button>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          {...common}
          variant="ghost"
          size="icon-sm"
          aria-label={status === "copied" ? `${name} season card copied` : label}
          className={cn("size-7 text-text-muted hover:text-text [&_svg:not([class*='size-'])]:size-3.5", className)}
        >
          {icon}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{status === "copied" ? "Copied. Paste it into Discord." : tooltip}</TooltipContent>
    </Tooltip>
  );
}
