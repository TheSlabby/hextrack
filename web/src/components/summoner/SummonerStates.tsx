import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { KeyRound, SearchX, Trophy, UserX } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { isApiError } from "@/api/client";
import { ErrorState, GlowCard, Kbd, Reveal } from "@/components/common";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { formatRiotId } from "@/lib/riotId";

import { RiotIdSearchForm } from "./RiotIdSearchForm";

interface StatePanelProps {
  icon: LucideIcon;
  tone?: "gold" | "loss";
  title: string;
  description: ReactNode;
  children?: ReactNode;
}

function StatePanel({ icon: Icon, tone = "gold", title, description, children }: StatePanelProps) {
  return (
    <Reveal>
      <GlowCard className="mx-auto mt-4 flex max-w-xl flex-col items-center gap-4 px-6 py-10 text-center sm:mt-10 sm:px-10 sm:py-12">
        <span
          className={cn(
            "flex size-14 items-center justify-center rounded-2xl border",
            tone === "gold" ? "border-gold/30 bg-gold/10 text-gold" : "border-loss/25 bg-loss/10 text-loss",
          )}
        >
          <Icon className="size-6" aria-hidden="true" />
        </span>
        <div className="flex max-w-md flex-col gap-1.5">
          <h1 className="font-display text-xl font-semibold text-balance text-text sm:text-2xl">{title}</h1>
          <div className="text-sm leading-relaxed text-text-secondary">{description}</div>
        </div>
        {children ? <div className="mt-1 flex w-full flex-col items-center gap-3">{children}</div> : null}
      </GlowCard>
    </Reveal>
  );
}

function PaletteHint() {
  return (
    <p className="flex items-center gap-1.5 text-xs text-text-muted">
      or press <Kbd>/</Kbd> anywhere to open search
    </p>
  );
}

function LeaderboardLink() {
  return (
    <Button variant="outline" size="sm" asChild>
      <Link to="/leaderboard">
        <Trophy aria-hidden="true" />
        Browse the roster leaderboard
      </Link>
    </Button>
  );
}

/** The URL slug has no "-TAG" part. */
export function InvalidRiotIdState({ slug, region }: { slug: string; region: string }) {
  return (
    <StatePanel
      icon={SearchX}
      title="That doesn't look like a Riot ID"
      description={
        <>
          <span className="font-medium text-text">{slug}</span> is missing its tag. Riot IDs look like{" "}
          <span className="font-medium text-text">Name#TAG</span>.
        </>
      }
    >
      <RiotIdSearchForm defaultValue={slug} region={region} />
      <PaletteHint />
    </StatePanel>
  );
}

export interface SummonerErrorStateProps {
  error: unknown;
  gameName: string;
  tagLine: string;
  region: string;
  onRetry: () => void;
}

/** Profile failed to load: 404, missing Riot key (503 riot_key) or anything else (with retry). */
export function SummonerErrorState({ error, gameName, tagLine, region, onRetry }: SummonerErrorStateProps) {
  const riotId = formatRiotId(gameName, tagLine);

  if (isApiError(error) && (error.status === 404 || error.code === "not_found")) {
    return (
      <StatePanel
        icon={UserX}
        title={`No summoner named ${riotId}`}
        description="Riot doesn't know this Riot ID. Check the spelling and the tag after the #, then search again."
      >
        <RiotIdSearchForm defaultValue={riotId} region={region} />
        <PaletteHint />
      </StatePanel>
    );
  }

  if (isApiError(error) && error.code === "invalid_riot_id") {
    return (
      <StatePanel icon={SearchX} title="That doesn't look like a Riot ID" description={error.detail}>
        <RiotIdSearchForm defaultValue={riotId} region={region} />
        <PaletteHint />
      </StatePanel>
    );
  }

  if (isApiError(error) && error.code === "riot_key") {
    const rejected = /reject|expired|invalid/i.test(error.detail);
    return (
      <StatePanel
        icon={KeyRound}
        title={
          rejected
            ? "This player isn't in HexTrack yet and the Riot API key was rejected"
            : "This player isn't in HexTrack yet and no Riot API key is configured"
        }
        description={
          <>
            HexTrack can only show players it has already stored until{" "}
            {rejected ? "the key is renewed" : "a key is set"} (<code className="font-mono text-xs text-text">RIOT_API_KEY</code>{" "}
            on the server). Roster players and anyone looked up before still work.
          </>
        }
      >
        <LeaderboardLink />
        <RiotIdSearchForm region={region} />
      </StatePanel>
    );
  }

  return (
    <Reveal>
      <GlowCard className="mx-auto mt-4 max-w-xl sm:mt-10">
        <ErrorState
          error={error}
          title={`Couldn't load ${riotId}`}
          onRetry={onRetry}
          action={
            <Button variant="ghost" size="sm" asChild>
              <Link to="/">Go home</Link>
            </Button>
          }
        />
      </GlowCard>
    </Reveal>
  );
}
