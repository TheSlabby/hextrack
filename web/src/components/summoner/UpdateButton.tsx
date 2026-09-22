import { Clock, Loader2, RefreshCw } from "lucide-react";

import { useHealth, useRefreshSummoner } from "@/api/queries";
import type { SummonerProfile } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { formatDuration, plural } from "@/lib/format";

import { useCountdown } from "./hooks";
import { parseTime } from "./summonerFormat";

export interface UpdateButtonProps {
  profile: SummonerProfile;
  /** "default" is the page's gold CTA; pass "outline" for a second Update inside a card. */
  variant?: "default" | "outline";
}

/**
 * The op.gg "Update" button: refreshes rank and pulls new games through Riot. Shows a spinner
 * while running and a live countdown until the per-player cooldown (`can_refresh_at`) ends.
 * Toasts for every outcome come from `useRefreshSummoner`.
 *
 * Blocked states use `aria-disabled` rather than `disabled`, so keyboard focus survives a click
 * (the button would otherwise drop focus the moment it disables) and the tooltip explaining
 * why it is blocked still opens on hover and focus.
 */
export function UpdateButton({ profile, variant = "default" }: UpdateButtonProps) {
  const refresh = useRefreshSummoner();
  const health = useHealth();

  const unlockCandidates = [parseTime(profile.can_refresh_at), parseTime(refresh.data?.next_allowed_at)].filter(
    (value): value is number => value !== null,
  );
  const unlockAt = unlockCandidates.length > 0 ? Math.max(...unlockCandidates) : null;
  const remaining = useCountdown(unlockAt);

  const keyMissing = health.data?.riot.key_configured === false;
  const pending = refresh.isPending;
  const cooling = remaining > 0 && !pending;
  const blocked = pending || cooling || keyMissing;

  const hint = keyMissing
    ? "Live updates need a Riot API key on the server. Stored data is still shown."
    : cooling
      ? "Recently updated. Each player can be refreshed once per cooldown."
      : null;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant={variant}
          onClick={() => {
            if (!blocked) refresh.mutate({ gameName: profile.game_name, tagLine: profile.tag_line });
          }}
          aria-disabled={blocked || undefined}
          aria-busy={pending || undefined}
          aria-label={
            pending
              ? "Updating"
              : cooling
                ? `Update available in ${cooldownLabel(remaining)}`
                : `Update ${profile.game_name}#${profile.tag_line}`
          }
          className={cn(
            "min-w-[7.5rem]",
            blocked && variant === "default" && "hover:from-[#d9bf86] hover:to-gold active:translate-y-0",
            blocked && variant !== "default" && "active:translate-y-0",
            pending ? "cursor-wait" : blocked && "cursor-not-allowed opacity-45",
          )}
        >
          {pending ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : cooling ? (
            <Clock aria-hidden="true" />
          ) : (
            <RefreshCw aria-hidden="true" />
          )}
          <span className="tabular-nums">{pending ? "Updating…" : cooling ? formatDuration(remaining) : "Update"}</span>
        </Button>
      </TooltipTrigger>
      {hint ? <TooltipContent>{hint}</TooltipContent> : null}
    </Tooltip>
  );
}

/** Minute-level wording for the accessible name, so screen readers aren't re-announced every second. */
function cooldownLabel(seconds: number): string {
  if (seconds < 60) return "less than a minute";
  return `about ${plural(Math.ceil(seconds / 60), "minute")}`;
}
