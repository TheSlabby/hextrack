import type { ReactNode } from "react";
import { Flame, History, Snowflake } from "lucide-react";

import { EmptyState, FormDots, GlowCard, SectionHeader } from "@/components/common";
import { cn } from "@/lib/cn";
import { formatPercent, formatRecord } from "@/lib/format";
import { currentStreak, PROFILE_FORM_LIMIT, streakInfo } from "@/lib/streaks";

export interface RecentFormCardProps {
  /** Ranked results, newest first (up to 20). */
  form: readonly boolean[];
  className?: string;
}

/** Last-20 strip in a 10-column grid with record, win rate and the current streak. */
export function RecentFormCard({ form, className }: RecentFormCardProps) {
  const results = form.slice(0, 20);
  const wins = results.filter(Boolean).length;
  const losses = results.length - wins;
  const streak = currentStreak(results, PROFILE_FORM_LIMIT);
  // 3+ in a row also gets a mood ("On fire") and a "+" when every game shown is part of it.
  const hot = streakInfo(results, PROFILE_FORM_LIMIT);
  const StreakIcon = hot?.win ? Flame : Snowflake;

  return (
    <GlowCard className={cn("flex flex-col gap-4 p-4 sm:p-5", className)}>
      <SectionHeader title="Recent form" eyebrow={`Last ${results.length || 20} ranked`} icon={History} size="sm" />
      {results.length === 0 ? (
        <EmptyState compact icon={History} title="No ranked games yet" description="Wins and losses show up here after ranked games." />
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2">
            <Figure label="Record" value={formatRecord(wins, losses)} />
            <Figure label="Win rate" value={formatPercent(wins / results.length)} />
            <Figure
              label="Streak"
              value={
                streak ? (
                  <span className="inline-flex items-center gap-1">
                    {hot ? (
                      <StreakIcon className={cn("size-4", hot.win ? "text-gold" : "text-loss")} aria-hidden="true" />
                    ) : null}
                    <span className={streak.win ? "text-win" : "text-loss"}>
                      {streak.length}
                      {hot?.open ? "+" : ""}
                      {streak.win ? "W" : "L"}
                    </span>
                  </span>
                ) : (
                  "–"
                )
              }
              note={
                hot ? (
                  <span className={hot.win ? "text-gold-bright" : "text-loss"} title={`${hot.description}. ${hot.mood}`}>
                    {hot.mood}
                  </span>
                ) : null
              }
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <FormDots
              results={results}
              limit={20}
              className="grid grid-cols-10 gap-1 [&>span]:h-7 [&>span]:w-full [&>span]:rounded-md [&>span]:text-[11px]"
            />
            <div className="flex justify-between text-[11px] text-text-muted" aria-hidden="true">
              <span>Newest</span>
              <span>Oldest</span>
            </div>
          </div>
        </>
      )}
    </GlowCard>
  );
}

function Figure({ label, value, note }: { label: string; value: ReactNode; note?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 rounded-xl border border-border bg-white/[0.02] px-3 py-2">
      <span className="label-caps truncate">{label}</span>
      <span className="font-display text-lg leading-tight font-semibold tabular-nums text-text">{value}</span>
      {note ? <span className="truncate text-[11px] leading-tight font-medium">{note}</span> : null}
    </div>
  );
}
