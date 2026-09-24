import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Copy, Download, Share2 } from "lucide-react";
import { toast } from "sonner";

import type { MatchDetail, ParticipantSummary } from "@/api/types";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useDdragon } from "@/lib/ddragon";

import { buildRecap, canCopyImage, copyImage, downloadBlob, renderRecapPng } from "./shareRecap";

export interface ShareRecapButtonProps {
  match: MatchDetail;
  player: ParticipantSummary;
  className?: string;
}

type Action = "copy" | "share" | "download";

const ACTIONS = {
  copy: { label: "Copy recap", menuLabel: "Copy image", icon: Copy },
  share: { label: "Share recap", menuLabel: "Share…", icon: Share2 },
  download: { label: "Download recap", menuLabel: "Download PNG", icon: Download },
} as const;

function canShareFiles(): boolean {
  return (
    typeof navigator.canShare === "function" &&
    window.matchMedia("(pointer: coarse)").matches &&
    navigator.canShare({ files: [new File([], "recap.png", { type: "image/png" })] })
  );
}

function toDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("Couldn't read the image"));
    reader.readAsDataURL(blob);
  });
}

/**
 * "Copy recap": one click puts the 1200x675 recap PNG on the clipboard, ready to paste into
 * Discord. The menu next to it downloads (or, on phones, shares) the same image. Where the
 * browser can't copy images, the main button downloads instead.
 */
export function ShareRecapButton({ match, player, className }: ShareRecapButtonProps) {
  const dd = useDdragon(match.patch);
  const [copied, setCopied] = useState(false);
  const [support] = useState(() => ({ copy: canCopyImage(), share: canShareFiles() }));
  // Rendered on first hover / focus / click and reused, keyed by match + player.
  const cache = useRef<{ key: string; blob: Promise<Blob> } | null>(null);

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 2_000);
    return () => window.clearTimeout(id);
  }, [copied]);

  const recap = () => buildRecap(match, player);
  const image = (): Promise<Blob> => {
    const key = `${match.match_id}:${player.puuid}`;
    if (cache.current?.key !== key) {
      const blob = renderRecapPng(recap(), dd.championSplash(player.champion_name));
      blob.catch(() => (cache.current = null));
      cache.current = { key, blob };
    }
    return cache.current.blob;
  };
  const filename = `hextrack-${match.match_id}-${player.game_name ?? player.champion_name}.png`.replace(/[^\w.-]+/g, "_");

  const onCopy = () => {
    // Synchronous with the click: Safari drops clipboard writes made after an await.
    const blob = image();
    copyImage(blob).then(
      async () => {
        setCopied(true);
        // A small preview in the toast, so it's clear what will be pasted.
        const src = await blob.then(toDataUrl).catch(() => null);
        toast.success("Recap copied. Paste it into Discord.", {
          description: src ? (
            <img src={src} alt={recap().alt} className="mt-2 aspect-[16/9] w-full rounded-md border border-border-strong" />
          ) : undefined,
        });
      },
      () => toast.error("Couldn't copy the image", { description: "Your browser blocked it. Use Download instead." }),
    );
  };
  const onDownload = () => {
    image().then(
      (blob) => downloadBlob(blob, filename),
      () => toast.error("Couldn't create the recap image"),
    );
  };
  const onShare = () => {
    image()
      .then((blob) => navigator.share({ files: [new File([blob], filename, { type: "image/png" })], title: recap().title }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        toast.error("Couldn't share the image", { description: "Use Download instead." });
      });
  };

  const warm = () => void image().catch(() => undefined);
  const run = (action: Action) => (action === "copy" ? onCopy() : action === "share" ? onShare() : onDownload());
  const primary: Action = support.copy ? "copy" : support.share ? "share" : "download";
  const menu: Action[] = [
    ...(support.copy && support.share ? (["share"] as const) : []),
    ...(support.copy || support.share ? (["download"] as const) : []),
  ];
  const PrimaryIcon = primary === "copy" && copied ? Check : ACTIONS[primary].icon;
  const primaryLabel = primary === "copy" && copied ? "Copied" : ACTIONS[primary].label;

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
                const Icon = ACTIONS[action].icon;
                return (
                  <DropdownMenuItem key={action} onSelect={() => run(action)}>
                    <Icon aria-hidden="true" />
                    {ACTIONS[action].menuLabel}
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
