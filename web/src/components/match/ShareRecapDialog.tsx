import { useEffect, useMemo, useState } from "react";
import { Check, Copy, Download, Share2 } from "lucide-react";
import { toast } from "sonner";

import type { MatchDetail, ParticipantSummary } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useDdragon } from "@/lib/ddragon";

import { allParticipants } from "./matchUtils";
import { buildRecap, canCopyImage, copyImage, downloadBlob, renderRecapPng, riotName } from "./shareRecap";

export interface ShareRecapDialogProps {
  match: MatchDetail;
  /** The player the card opens on (the focused player, or the hero pick). */
  initialPlayer: ParticipantSummary;
}

/** "Share recap" button + dialog: previews the 1200x675 recap PNG and copies, shares or downloads it. */
export function ShareRecapDialog({ match, initialPlayer }: ShareRecapDialogProps) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Share2 aria-hidden="true" />
          Share recap
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Share this game</DialogTitle>
          <DialogDescription>A recap image sized for Discord. Copy it and paste it straight into a channel.</DialogDescription>
        </DialogHeader>
        {open ? <ShareRecapBody match={match} initialPlayer={initialPlayer} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function ShareRecapBody({ match, initialPlayer }: ShareRecapDialogProps) {
  const dd = useDdragon(match.patch);
  const players = useMemo(() => {
    const tracked = allParticipants(match).filter((p) => p.is_tracked || p.puuid === initialPlayer.puuid);
    return tracked.length > 0 ? tracked : [initialPlayer];
  }, [match, initialPlayer]);
  const [puuid, setPuuid] = useState(initialPlayer.puuid);
  const player = players.find((p) => p.puuid === puuid) ?? initialPlayer;
  const recap = useMemo(() => buildRecap(match, player), [match, player]);
  const splashUrl = dd.championSplash(player.champion_name);

  // One render per player; the pending promise itself is what the clipboard receives (see copyImage).
  const blob = useMemo(() => {
    const pending = renderRecapPng(recap, splashUrl);
    pending.catch(() => undefined);
    return pending;
  }, [recap, splashUrl]);

  const [rendered, setRendered] = useState<{ blob: Promise<Blob>; url: string | null } | null>(null);
  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    blob.then(
      (result) => {
        if (cancelled) return;
        url = URL.createObjectURL(result);
        setRendered({ blob, url });
      },
      () => !cancelled && setRendered({ blob, url: null }),
    );
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [blob]);
  const current = rendered?.blob === blob ? rendered : null;
  const preview = current?.url ?? null;
  const failed = current !== null && current.url === null;

  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 2_000);
    return () => window.clearTimeout(id);
  }, [copied]);

  const filename = `hextrack-${match.match_id}-${player.game_name ?? player.champion_name}.png`.replace(/[^\w.-]+/g, "_");
  const copySupported = useMemo(() => canCopyImage(), []);
  const shareSupported = useMemo(
    () =>
      typeof navigator.canShare === "function" &&
      window.matchMedia("(pointer: coarse)").matches &&
      navigator.canShare({ files: [new File([], filename, { type: "image/png" })] }),
    [filename],
  );

  const onCopy = () => {
    copyImage(blob).then(
      () => {
        setCopied(true);
        toast.success("Recap copied", { description: "Paste it into Discord." });
      },
      () => toast.error("Couldn't copy the image", { description: "Your browser blocked it. Download it instead." }),
    );
  };
  const onDownload = () => {
    blob.then(
      (result) => downloadBlob(result, filename),
      () => toast.error("Couldn't create the recap image"),
    );
  };
  const onShare = () => {
    blob
      .then((result) => navigator.share({ files: [new File([result], filename, { type: "image/png" })], title: recap.title }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        toast.error("Couldn't share the image", { description: "Download it instead." });
      });
  };

  const busy = !preview && !failed;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {players.length > 1 ? (
        <Select value={puuid} onValueChange={setPuuid}>
          <SelectTrigger className="w-full sm:w-72" aria-label="Player on the recap">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {players.map((p) => (
              <SelectItem key={p.puuid} value={p.puuid}>
                {riotName(p)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}

      <div className="aspect-[16/9] w-full overflow-hidden rounded-xl border border-border-strong bg-bg" aria-busy={busy}>
        {preview ? (
          <img src={preview} alt={recap.alt} className="size-full" />
        ) : failed ? (
          <p role="alert" className="flex size-full items-center justify-center p-6 text-center text-sm text-text-secondary">
            Couldn't draw the recap image in this browser.
          </p>
        ) : (
          <Skeleton className="size-full rounded-none" aria-label="Drawing the recap" />
        )}
      </div>

      <div className="flex flex-wrap justify-end gap-2">
        {shareSupported ? (
          <Button variant="outline" onClick={onShare} disabled={busy || failed}>
            <Share2 aria-hidden="true" />
            Share
          </Button>
        ) : null}
        <Button variant={copySupported ? "outline" : "default"} onClick={onDownload} disabled={busy || failed}>
          <Download aria-hidden="true" />
          Download PNG
        </Button>
        {copySupported ? (
          <Button onClick={onCopy} disabled={busy || failed}>
            {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
            {copied ? "Copied" : "Copy image"}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
