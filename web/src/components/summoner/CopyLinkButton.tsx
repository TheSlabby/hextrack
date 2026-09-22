import { useEffect, useState } from "react";
import { Check, Link2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { summonerPath } from "@/lib/riotId";

export interface CopyLinkButtonProps {
  gameName: string;
  tagLine: string;
  region: string;
}

/** Copies the canonical profile URL to the clipboard. */
export function CopyLinkButton({ gameName, tagLine, region }: CopyLinkButtonProps) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 2_000);
    return () => window.clearTimeout(id);
  }, [copied]);

  const copy = async () => {
    const url = `${window.location.origin}${summonerPath(gameName, tagLine, region)}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      toast.success("Profile link copied", { description: url });
    } catch {
      toast.error("Couldn't copy the link", { description: url });
    }
  };

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="outline" size="icon" onClick={() => void copy()} aria-label="Copy profile link">
          {copied ? <Check className="text-score-a" aria-hidden="true" /> : <Link2 aria-hidden="true" />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{copied ? "Copied" : "Copy profile link"}</TooltipContent>
    </Tooltip>
  );
}
