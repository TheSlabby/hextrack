import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Copy, Download, Share2, User } from "lucide-react";
import type { MatchDetail, ParticipantSummary } from "@/api/types";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useQueryClient } from "@tanstack/react-query";

import { squadPairsQuery } from "@/api/queries";
import { useDdragon } from "@/lib/ddragon";

import {
  buildGroupRecap,
  buildRecap,
  canCopyImage,
  groupMembers,
  renderGroupRecapPng,
  renderRecapPng,
  type PairRecord,
} from "./shareRecap";
import { canShareFiles, copyWithToast, downloadWithToast, shareWithToast } from "./shareActions";

export interface ShareRecapButtonProps {
  match: MatchDetail;
  player: ParticipantSummary;
  className?: string;
}

type Action = "copy" | "copySolo" | "share" | "download";
/** Which card: just the player, or them with their tracked teammates. */
type Variant = "solo" | "group";

const ICONS = { copy: Copy, copySolo: User, share: Share2, download: Download } as const;

/**
 * "Copy recap": one click puts the 1200x675 recap PNG on the clipboard, ready to paste into
 * Discord. When tracked friends were on the player's team it copies the duo / squad card, and
 * the menu has "Just me" for the solo one. The menu also downloads (or, on phones, shares) the
 * image. Where the browser can't copy images, the main button downloads instead.
 */
export function ShareRecapButton({ match, player, className }: ShareRecapButtonProps) {
  const dd = useDdragon(match.patch);
  const queryClient = useQueryClient();
  const [copied, setCopied] = useState(false);
  const [support] = useState(() => ({ copy: canCopyImage(), share: canShareFiles() }));
  // Rendered on first hover / focus / click and reused, keyed by match + player + variant.
  const cache = useRef<Map<string, Promise<Blob>>>(new Map());

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 2_000);
    return () => window.clearTimeout(id);
  }, [copied]);

  const members = groupMembers(match, player);
  const groupWord = members.length === 2 ? "duo" : members.length > 2 ? "squad" : null;
  const defaultVariant: Variant = groupWord ? "group" : "solo";

  /** Season record for a duo, from the squad endpoint (cached with the Squad page's query). */
  const pairRecord = async (): Promise<PairRecord | null> => {
    const [a, b] = members;
    if (members.length !== 2 || !a || !b) return null;
    const data = await queryClient.fetchQuery(squadPairsQuery("season", "all")).catch(() => null);
    const pair = data?.pairs.find(
      (p) => (p.a_puuid === a.puuid && p.b_puuid === b.puuid) || (p.a_puuid === b.puuid && p.b_puuid === a.puuid),
    );
    return pair ? { games: pair.games, wins: pair.wins } : null;
  };
  const describe = (variant: Variant) => (variant === "group" ? buildGroupRecap(match, members, null) : buildRecap(match, player));
  const image = (variant: Variant): Promise<Blob> => {
    const key = `${match.match_id}:${player.puuid}:${variant}`;
    let blob = cache.current.get(key);
    if (!blob) {
      const splash = dd.championSplash(player.champion_name);
      blob =
        variant === "group"
          ? pairRecord().then((pair) =>
              renderGroupRecapPng(
                buildGroupRecap(match, members, pair),
                splash,
                members.map((m) => dd.championIcon(m.champion_name)),
              ),
            )
          : renderRecapPng(buildRecap(match, player), splash);
      blob.catch(() => cache.current.delete(key));
      cache.current.set(key, blob);
    }
    return blob;
  };
  const filename = (variant: Variant) =>
    `hextrack-${match.match_id}-${player.game_name ?? player.champion_name}${variant === "group" ? `-${groupWord}` : ""}.png`.replace(/[^\w.-]+/g, "_");

  const onCopy = (variant: Variant) => {
    // Synchronous with the click: Safari drops clipboard writes made after an await.
    void copyWithToast(image(variant), {
      message: `${variant === "group" && groupWord ? `${groupWord === "duo" ? "Duo" : "Squad"} recap` : "Recap"} copied. Paste it into Discord.`,
      alt: () => describe(variant).alt,
    }).then((ok) => ok && setCopied(true));
  };
  const onDownload = (variant: Variant) => {
    void downloadWithToast(image(variant), filename(variant), "Couldn't create the recap image");
  };
  const onShare = (variant: Variant) => {
    void shareWithToast(image(variant), filename(variant), describe(variant).title);
  };

  const warm = () => void image(defaultVariant).catch(() => undefined);
  const run = (action: Action) => {
    if (action === "copy") onCopy(defaultVariant);
    else if (action === "copySolo") onCopy("solo");
    else if (action === "share") onShare(defaultVariant);
    else onDownload(defaultVariant);
  };
  const primary: Action = support.copy ? "copy" : support.share ? "share" : "download";
  const menu: Action[] = [
    ...(support.copy && groupWord ? (["copySolo"] as const) : []),
    ...(support.copy && support.share ? (["share"] as const) : []),
    ...(support.copy || support.share ? (["download"] as const) : []),
  ];
  const noun = groupWord ? `${groupWord} recap` : "recap";
  const labels: Record<Action, string> = {
    copy: `Copy ${noun}`,
    copySolo: "Copy just me",
    share: primary === "share" ? `Share ${noun}` : "Share…",
    download: primary === "download" ? `Download ${noun}` : "Download PNG",
  };
  const PrimaryIcon = primary === "copy" && copied ? Check : ICONS[primary];
  const primaryLabel = primary === "copy" && copied ? "Copied" : labels[primary];

  return (
    <div className={className} onPointerEnter={warm} onFocus={warm}>
      <div className="inline-flex">
        <Button
          variant="outline"
          size="sm"
          onClick={() => run(primary)}
          className={menu.length > 0 ? "rounded-r-none" : undefined}
          aria-label={`${primaryLabel}: an image of this game for Discord`}
        >
          <PrimaryIcon aria-hidden="true" className={copied ? "text-score-a" : undefined} />
          {primaryLabel}
        </Button>
        {menu.length > 0 ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="icon-sm" className="-ml-px rounded-l-none" aria-label="More share options">
                <ChevronDown aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {menu.map((action) => {
                const Icon = ICONS[action];
                return (
                  <DropdownMenuItem key={action} onSelect={() => run(action)}>
                    <Icon aria-hidden="true" />
                    {labels[action]}
                  </DropdownMenuItem>
                );
              })}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>
    </div>
  );
}
