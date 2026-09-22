import { Bug, Castle, Crown, Droplet, Eye, Flame, Gem, Skull, type LucideIcon } from "lucide-react";

import type { ObjectiveStat, TeamObjectives as TeamObjectivesData } from "@/api/types";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ChampionIcon } from "@/components/common/ChampionIcon";
import { cn } from "@/lib/cn";

import { useChampionCatalog, type ChampionCatalog } from "./useChampionCatalog";

type ObjectiveKey = Exclude<keyof TeamObjectivesData, "champion">;

interface ObjectiveSpec {
  key: ObjectiveKey;
  label: string;
  singular: string;
  plural: string;
  icon: LucideIcon;
}

const OBJECTIVES: readonly ObjectiveSpec[] = [
  { key: "tower", label: "Towers", singular: "tower", plural: "towers", icon: Castle },
  { key: "inhibitor", label: "Inhibitors", singular: "inhibitor", plural: "inhibitors", icon: Gem },
  { key: "dragon", label: "Dragons", singular: "dragon", plural: "dragons", icon: Flame },
  { key: "horde", label: "Voidgrubs", singular: "voidgrub", plural: "voidgrubs", icon: Bug },
  { key: "rift_herald", label: "Rift Herald", singular: "Rift Herald", plural: "Rift Heralds", icon: Eye },
  { key: "baron", label: "Baron Nashor", singular: "Baron", plural: "Barons", icon: Crown },
  { key: "atakhan", label: "Atakhan", singular: "Atakhan", plural: "Atakhans", icon: Skull },
];

function describe(spec: ObjectiveSpec, stat: ObjectiveStat): string {
  const noun = stat.kills === 1 ? spec.singular : spec.plural;
  return `${stat.kills} ${noun}${stat.first ? `, took the first ${spec.singular}` : ""}`;
}

function ObjectiveChip({ spec, stat }: { spec: ObjectiveSpec; stat: ObjectiveStat }) {
  const Icon = spec.icon;
  const none = stat.kills === 0;
  const text = describe(spec, stat);
  return (
    <li>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "relative inline-flex h-6 items-center gap-1 rounded-md border px-1.5 text-xs font-semibold tabular-nums",
              none ? "border-border bg-transparent text-text-muted" : "border-border bg-white/[0.04] text-text",
              stat.first && "border-gold/35",
            )}
            role="img"
            aria-label={text}
          >
            <Icon
              className={cn("size-3.5", stat.first ? "text-gold" : none ? "text-text-muted" : "text-text-secondary")}
              aria-hidden="true"
            />
            {stat.kills}
            {stat.first ? (
              <span aria-hidden="true" className="absolute -top-1 -right-1 size-2 rounded-full border border-surface-1 bg-gold" />
            ) : null}
          </span>
        </TooltipTrigger>
        <TooltipContent>
          <span className="font-semibold text-text">{spec.label}</span>
          <span className="text-text-secondary"> · {text}</span>
        </TooltipContent>
      </Tooltip>
    </li>
  );
}

function FirstMarker({ icon: Icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <li>
      <span className="inline-flex h-6 items-center gap-1 rounded-md border border-gold/35 bg-gold/10 px-1.5 text-[11px] font-semibold text-gold">
        <Icon className="size-3.5" aria-hidden="true" />
        {label}
      </span>
    </li>
  );
}

/**
 * Objective counts for one team (towers, inhibitors, dragons, grubs, heralds, barons and
 * Atakhan when present) plus "First blood" / "First tower" markers. A gold dot marks every
 * objective the team took first; the tooltip and label say so in words.
 */
export function TeamObjectives({ objectives, className }: { objectives: TeamObjectivesData; className?: string }) {
  const specs = OBJECTIVES.filter((spec) => objectives[spec.key] !== null && objectives[spec.key] !== undefined);
  return (
    <ul className={cn("flex flex-wrap items-center gap-1.5", className)} aria-label="Objectives">
      {objectives.champion.first ? <FirstMarker icon={Droplet} label="First blood" /> : null}
      {objectives.tower.first ? <FirstMarker icon={Castle} label="First tower" /> : null}
      {specs.map((spec) => {
        const stat = objectives[spec.key];
        return stat ? <ObjectiveChip key={spec.key} spec={spec} stat={stat} /> : null;
      })}
    </ul>
  );
}

// --- bans ---------------------------------------------------------------------------------

function BanSlot({ championId, catalog, loading }: { championId: number; catalog: ChampionCatalog | undefined; loading: boolean }) {
  if (championId <= 0) {
    return (
      <span
        className="block size-5 rounded-md border border-dashed border-border-strong"
        role="img"
        aria-label="No ban"
        title="No ban"
      />
    );
  }
  const champion = catalog?.get(championId);
  if (!champion) {
    if (loading) return <Skeleton className="size-5 rounded-md" />;
    return (
      <span
        className="flex size-5 items-center justify-center rounded-md bg-surface-3 text-[10px] font-semibold text-text-muted ring-1 ring-white/10"
        role="img"
        aria-label={`Banned champion ${championId}`}
        title={`Champion ${championId}`}
      >
        ?
      </span>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="relative block size-5" role="img" aria-label={`Banned ${champion.name}`}>
          <ChampionIcon champion={champion.key} size="xs" className="opacity-70 grayscale-[0.85]" />
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 rounded-md bg-[linear-gradient(135deg,transparent_45%,var(--color-loss)_46%,var(--color-loss)_54%,transparent_55%)] opacity-75"
          />
        </span>
      </TooltipTrigger>
      <TooltipContent>Banned {champion.name}</TooltipContent>
    </Tooltip>
  );
}

/** A team's bans in pick-turn order (hidden when the queue has no bans). */
export function TeamBans({ bans, className }: { bans: readonly number[]; className?: string }) {
  const hasBans = bans.length > 0;
  const catalog = useChampionCatalog(hasBans && bans.some((id) => id > 0));
  if (!hasBans) return null;
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="label-caps">Bans</span>
      <ul className="flex items-center gap-1" aria-label="Bans">
        {bans.map((id, index) => (
          <li key={`${index}-${id}`}>
            <BanSlot championId={id} catalog={catalog.data} loading={catalog.isPending} />
          </li>
        ))}
      </ul>
    </div>
  );
}
