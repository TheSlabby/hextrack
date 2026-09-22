import type { ReactNode } from "react";
import { KeyRound, RefreshCw, SearchX, ServerCrash, Timer, TriangleAlert, WifiOff } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { isApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

export interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
  /** Override the title (e.g. "Couldn't load matches"). */
  title?: string;
  /** Extra actions next to Retry. */
  action?: ReactNode;
  compact?: boolean;
  className?: string;
}

interface ErrorCopy {
  icon: LucideIcon;
  title: string;
  description: string;
  retry: boolean;
}

function describe(error: unknown): ErrorCopy {
  if (isApiError(error)) {
    switch (error.code) {
      case "riot_key":
        return {
          icon: KeyRound,
          title: "Riot API key not configured",
          description:
            "HexTrack can't reach Riot right now, so new players and fresh games can't be loaded. Stored data still works. Set RIOT_API_KEY on the server.",
          retry: false,
        };
      case "riot_rate_limited":
        return {
          icon: Timer,
          title: "Riot rate limit reached",
          description: error.retryAfter
            ? `Too many requests to Riot. Try again in ${error.retryAfter}s.`
            : "Too many requests to Riot. Try again in a moment.",
          retry: true,
        };
      case "riot_unavailable":
        return { icon: ServerCrash, title: "Riot API unavailable", description: error.detail, retry: true };
      case "network":
        return { icon: WifiOff, title: "Can't reach HexTrack", description: error.detail, retry: true };
      case "model_missing":
        return {
          icon: TriangleAlert,
          title: "AI model not trained",
          description: "Train a model with `hextrack train --activate` to enable AI Scores.",
          retry: false,
        };
    }
    if (error.status === 404) {
      return { icon: SearchX, title: "Not found", description: error.detail, retry: false };
    }
    return {
      icon: TriangleAlert,
      title: "Something went wrong",
      description: error.detail,
      retry: error.status >= 500 || error.status === 0,
    };
  }
  return {
    icon: TriangleAlert,
    title: "Something went wrong",
    description: error instanceof Error ? error.message : "An unexpected error occurred.",
    retry: true,
  };
}

/** Friendly error block with copy tailored to the API error code and a Retry button. */
export function ErrorState({ error, onRetry, title, action, compact, className }: ErrorStateProps) {
  const copy = describe(error);
  const Icon = copy.icon;
  const riotKey = isApiError(error) && error.code === "riot_key";
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "gap-2 px-4 py-6" : "gap-3 px-6 py-12",
        className,
      )}
    >
      <span
        className={cn(
          "flex items-center justify-center rounded-2xl border",
          compact ? "size-10" : "size-14",
          riotKey ? "border-gold/30 bg-gold/10 text-gold" : "border-loss/25 bg-loss/10 text-loss",
        )}
      >
        <Icon className={compact ? "size-5" : "size-6"} aria-hidden="true" />
      </span>
      <div className="flex max-w-md flex-col gap-1">
        <p className={cn("font-display font-semibold text-text", compact ? "text-sm" : "text-base")}>{title ?? copy.title}</p>
        <p className="text-sm leading-relaxed text-text-secondary">{copy.description}</p>
      </div>
      {(onRetry && copy.retry) || action ? (
        <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
          {onRetry && copy.retry ? (
            <Button variant="outline" size="sm" onClick={onRetry}>
              <RefreshCw aria-hidden="true" />
              Try again
            </Button>
          ) : null}
          {action}
        </div>
      ) : null}
    </div>
  );
}
