import { Users } from "lucide-react";

import { EmptyState } from "@/components/common/EmptyState";
import { GlowCard } from "@/components/common/GlowCard";
import { cn } from "@/lib/cn";

function Command({ children }: { children: string }) {
  return (
    <code className="rounded-md border border-border-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[12px] whitespace-nowrap text-gold-bright">
      {children}
    </code>
  );
}

/** Shown when nobody is tracked yet: explains how to add players or load demo data. */
export function RosterEmptyState({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <GlowCard className={cn(className)}>
      <EmptyState
        icon={Users}
        compact={compact}
        title="Nobody on the roster yet"
        description={
          <div className="flex flex-col gap-2">
            <p>
              Track your friends with <Command>hextrack roster add "Name#TAG"</Command> and HexTrack keeps their games,
              LP and AI Scores up to date.
            </p>
            <p>
              Just exploring? Load sample players with <Command>hextrack seed-demo</Command>.
            </p>
          </div>
        }
      />
    </GlowCard>
  );
}
