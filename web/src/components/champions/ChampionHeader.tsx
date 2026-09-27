import { TriangleAlert } from "lucide-react";

import type { ChampionDetail, ChampionPatchParam, ChampionRole, ChampionRoleSummary, LeaderboardQueue } from "@/api/types";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { PositionIcon } from "@/components/common/PositionIcon";
import { QueueToggle } from "@/components/leaderboard/QueueToggle";
import { ProfileBanner } from "@/components/summoner/ProfileBanner";
import { Skeleton } from "@/components/ui/skeleton";
import { championDisplayName, patchWindowLabel } from "@/lib/champions";
import { cn } from "@/lib/cn";
import { formatInteger, formatPercent, plural } from "@/lib/format";
import { POSITION_LABELS, POSITION_LONG_LABELS } from "@/lib/positions";

import { pct } from "./detailModel";
import { ChampionStatStrip } from "./ChampionStatStrip";
import { ChampionTierBadge } from "./ChampionTierBadge";
import { PatchSelect } from "./PatchSelect";

const QUEUE_LABEL: Readonly<Record<LeaderboardQueue, string>> = {
  all: "Ranked Solo/Duo and Flex",
  solo: "Ranked Solo/Duo",
  flex: "Ranked Flex",
};

export interface ChampionHeaderProps {
  /** Data Dragon key once known (null while the first response loads). */
  champion: string | null;
  detail: ChampionDetail | undefined;
  patch: ChampionPatchParam;
  queue: LeaderboardQueue;
  onPatchChange: (patch: ChampionPatchParam) => void;
  onQueueChange: (queue: LeaderboardQueue) => void;
  onRoleChange: (role: ChampionRole) => void;
}

function RoleTab({ role, active, onSelect }: { role: ChampionRoleSummary; active: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onSelect}
      aria-label={`${POSITION_LONG_LABELS[role.position]}: ${role.tier ? `${role.tier} tier, ` : ""}${plural(role.games, "game")}, ${formatPercent(role.share)} of games, ${pct(role.win_rate)} win rate`}
      className={cn(
        "flex shrink-0 items-center gap-2 rounded-xl border px-3 py-2 text-left transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold",
        active
          ? "border-gold/45 bg-gold/[0.08] text-gold-bright"
          : "border-border bg-surface-1/70 text-text-secondary hover:border-border-strong hover:text-text",
      )}
    >
      <PositionIcon position={role.position} size={18} title="" />
      <span className="flex flex-col" aria-hidden="true">
        <span className="text-sm leading-tight font-semibold">{POSITION_LABELS[role.position]}</span>
        <span className="text-[11px] leading-tight text-text-muted tabular-nums">
          {formatInteger(role.games)} · {formatPercent(role.share)}
        </span>
      </span>
      {role.tier ? <ChampionTierBadge tier={role.tier} tooltip={false} className="ml-1" /> : null}
    </button>
  );
}

/** Champion hero: splash backdrop, icon and name, patch / queue filters, role tabs and the headline rates. */
export function ChampionHeader({
  champion,
  detail,
  patch,
  queue,
  onPatchChange,
  onQueueChange,
  onRoleChange,
}: ChampionHeaderProps) {
  const name = champion ? championDisplayName(champion) : null;
  const role = detail?.role ?? null;
  // Tabs: the roles the API shows, plus the active one if it was asked for by URL.
  const roles = detail?.roles.filter((r) => r.shown || r.position === role) ?? [];
  const roleSummary = detail?.roles.find((r) => r.position === role) ?? null;
  const stats = detail?.detail?.stats;
  const windowLabel = detail ? patchWindowLabel(detail.patch, detail.patches) : null;

  return (
    <header className="relative isolate flex flex-col gap-4 pt-2 sm:pt-6">
      <ProfileBanner champion={champion} />

      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex min-w-0 items-center gap-4 sm:gap-5">
          {champion ? (
            <ChampionIcon champion={champion} size="xl" className="shadow-[0_0_32px_-8px_rgba(200,170,110,0.55)]" />
          ) : (
            <Skeleton className="size-20 shrink-0 rounded-lg" />
          )}
          <div className="flex min-w-0 flex-col gap-1.5">
            <span className="label-caps">
              Champion{role ? ` · ${POSITION_LONG_LABELS[role]}` : ""}
            </span>
            {name ? (
              <div className="flex min-w-0 items-center gap-3">
                <h1 className="min-w-0 font-display text-[28px] leading-[1.1] font-bold tracking-tight [overflow-wrap:anywhere] text-text sm:text-4xl">
                  {name}
                </h1>
                {role && roleSummary ? (
                  <ChampionTierBadge tier={roleSummary.tier} role={role} size="md" focusable />
                ) : null}
              </div>
            ) : (
              <Skeleton className="h-8 w-44 sm:h-10" />
            )}
            <p className="text-sm text-text-secondary">
              {windowLabel ?? " "}
              {windowLabel ? <span className="text-text-muted"> · {QUEUE_LABEL[queue]}</span> : null}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PatchSelect value={patch} onChange={onPatchChange} />
          <QueueToggle value={queue} onChange={onQueueChange} />
        </div>
      </div>

      {detail ? (
        roles.length > 0 ? (
          <div className="scrollbar-thin -mx-1 flex gap-2 overflow-x-auto px-1 pb-1" role="group" aria-label="Role">
            {roles.map((r) => (
              <RoleTab key={r.position} role={r} active={r.position === role} onSelect={() => onRoleChange(r.position)} />
            ))}
          </div>
        ) : null
      ) : (
        <div className="flex gap-2" aria-hidden="true">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-[3.25rem] w-28 rounded-xl" />
          ))}
        </div>
      )}

      <ChampionStatStrip detail={detail} />

      {stats?.small_sample ? (
        <p className="flex items-start gap-2 text-sm text-text-secondary">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-gold" aria-hidden="true" />
          <span>
            Only {plural(stats.games, "game")} here, so these numbers can swing a lot.
            {patch !== "season" ? " Pick “Whole season” for a bigger sample." : ""}
          </span>
        </p>
      ) : null}
    </header>
  );
}
