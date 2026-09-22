import { useMemo, useState } from "react";
import { ChevronDown, Coins, Eye, HeartPulse, Layers, Swords, TowerControl, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { motion } from "motion/react";

import type { FeatureAttribution, FeatureGroup } from "@/api/types";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { CHART_COLORS, divergingColor } from "@/lib/chartTheme";
import { formatPercent } from "@/lib/format";
import { EASE_OUT, MOTION, staggerStep, useEntranceMotion } from "@/lib/motion";

import {
  FEATURE_GROUP_LABELS,
  FEATURE_GROUP_ORDER,
  buildDrivers,
  explainDriver,
  formatShare,
  type DriverDisplay,
} from "./insights";
import { LegendKey } from "./parts";

/** Rows shown before "Show all". */
const TOP_N = 10;


const FEATURE_GROUP_ICONS: Readonly<Record<FeatureGroup, LucideIcon>> = {
  combat: Swords,
  economy: Coins,
  vision: Eye,
  objectives: TowerControl,
  survival: HeartPulse,
  teamplay: Users,
};

type GroupFilter = FeatureGroup | "all";

export interface AttributionChartProps {
  features: readonly FeatureAttribution[];
}

/** Neutral and mixed-signal families are grey: the bar still shows the direction, the colour says "don't lean on it". */
function driverColor(driver: DriverDisplay): string {
  return driver.neutral || driver.mixed ? CHART_COLORS.neutral : divergingColor(driver.attribution);
}

function signedShare(driver: DriverDisplay): number {
  return Math.sign(driver.attribution) * driver.share;
}

/**
 * Diverging horizontal bars, one per stat family (deaths per game, per minute and per gold
 * count as one "Deaths" bar): families that lift the score extend right (teal), those that
 * cost score extend left (red). Values are each family's share of the model's total
 * influence, sorted largest first; group chips filter.
 */
export function AttributionChart({ features }: AttributionChartProps) {
  const [group, setGroup] = useState<GroupFilter>("all");
  const [expanded, setExpanded] = useState(false);

  const drivers = useMemo(() => buildDrivers(features), [features]);
  // One scale for every filter, so a group's bars stay comparable with the full list.
  const maxShare = useMemo(() => Math.max(0.05, ...drivers.map((d) => d.share)), [drivers]);

  const counts = useMemo(() => {
    const out: Record<GroupFilter, number> = {
      all: drivers.length,
      combat: 0,
      economy: 0,
      vision: 0,
      objectives: 0,
      survival: 0,
      teamplay: 0,
    };
    for (const d of drivers) out[d.group] += 1;
    return out;
  }, [drivers]);

  const filtered = group === "all" ? drivers : drivers.filter((d) => d.group === group);
  const visible = expanded ? filtered : filtered.slice(0, TOP_N);
  const hidden = filtered.length - visible.length;
  const showsMixed = visible.some((d) => d.mixed);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <ToggleGroup
        type="single"
        value={group}
        onValueChange={(next) => {
          if (!next) return;
          setGroup(next as GroupFilter);
          setExpanded(false);
        }}
        aria-label="Filter stats by group"
        className="w-full flex-wrap gap-1.5 rounded-none border-0 bg-transparent p-0"
      >
        <GroupChip value="all" label="All" icon={Layers} count={counts.all} />
        {FEATURE_GROUP_ORDER.map((g) => (
          <GroupChip key={g} value={g} label={FEATURE_GROUP_LABELS[g]} icon={FEATURE_GROUP_ICONS[g]} count={counts[g]} />
        ))}
      </ToggleGroup>

      <div className="flex flex-col">
        <ScaleHeader showsMixed={showsMixed} />
        <ul className="flex flex-col" aria-label="Stat influence on the AI Score">
          {visible.map((driver, i) => (
            <AttributionRow key={driver.key} driver={driver} maxShare={maxShare} order={i} />
          ))}
        </ul>
        <ScaleFooter maxShare={maxShare} />
      </div>

      {filtered.length > TOP_N ? (
        <div className="flex justify-center">
          <Button variant="ghost" size="sm" onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
            {expanded ? `Show top ${TOP_N}` : `Show all ${filtered.length} stats`}
            <ChevronDown
              className={cn("transition-transform duration-200", expanded && "rotate-180")}
              aria-hidden="true"
            />
            {!expanded && hidden > 0 ? <span className="sr-only">({hidden} more)</span> : null}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function GroupChip({ value, label, icon: Icon, count }: { value: GroupFilter; label: string; icon: LucideIcon; count: number }) {
  return (
    <ToggleGroupItem
      value={value}
      disabled={count === 0}
      aria-label={`${label} (${count} stats)`}
      className={cn(
        "h-7 gap-1.5 rounded-full border border-border bg-surface-2/50 px-3 text-xs text-text-secondary",
        "hover:border-border-strong",
        "data-[state=on]:border-cyan/40 data-[state=on]:bg-cyan/10 data-[state=on]:text-cyan data-[state=on]:shadow-none",
      )}
    >
      <Icon className="hidden size-3.5 sm:block" aria-hidden="true" />
      {label}
      <span className="tabular-nums text-text-muted">{count}</span>
    </ToggleGroupItem>
  );
}

/** Column grid shared by the header, rows and footer so the bars line up. */
const ROW_GRID =
  "grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 sm:grid-cols-[minmax(0,15rem)_minmax(0,1fr)_3.5rem] lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)_3.75rem]";

function ScaleHeader({ showsMixed }: { showsMixed: boolean }) {
  return (
    <div className={cn(ROW_GRID, "items-end gap-y-1.5 pb-2 text-[11px] text-text-muted")} aria-hidden="true">
      <span className="hidden font-semibold tracking-[0.08em] uppercase sm:block">Stat</span>
      <div className="col-span-2 flex flex-col gap-1 sm:col-span-1">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-1.5">
            <LegendKey color={CHART_COLORS.negative} mark="bar" />
            Lowers score
          </span>
          <span className="flex items-center gap-1.5">
            Raises score
            <LegendKey color={CHART_COLORS.positive} mark="bar" />
          </span>
        </div>
        {showsMixed ? (
          <span className="flex items-center justify-center gap-1.5">
            <LegendKey color={CHART_COLORS.neutral} mark="bar" />
            Mixed signal
          </span>
        ) : null}
      </div>
      <span className="hidden text-right font-semibold tracking-[0.08em] uppercase sm:block">Share</span>
    </div>
  );
}

function ScaleFooter({ maxShare }: { maxShare: number }) {
  return (
    <div className={cn(ROW_GRID, "pt-1.5 text-[11px] tabular-nums text-text-muted")} aria-hidden="true">
      <span className="hidden sm:block" />
      <div className="relative col-span-2 h-4 sm:col-span-1">
        <span className="absolute left-0">{formatShare(-maxShare)}</span>
        <span className="absolute left-1/2 -translate-x-1/2">0</span>
        <span className="absolute right-0">{formatShare(maxShare)}</span>
      </div>
      <span className="hidden sm:block" />
    </div>
  );
}

function effectText(driver: DriverDisplay): string {
  if (driver.neutral) return "no real effect";
  return driver.attribution > 0 ? "raises the score" : "lowers the score";
}

function AttributionRow({ driver, maxShare, order }: { driver: DriverDisplay; maxShare: number; order: number }) {
  const entrance = useEntranceMotion();
  const { headline, neutral, mixed } = driver;
  const positive = driver.attribution > 0;
  const width = neutral ? 0 : Math.max(0.6, (driver.share / maxShare) * 50);
  const color = driverColor(driver);
  const Icon = FEATURE_GROUP_ICONS[driver.group];
  const share = formatShare(signedShare(driver));
  const unit = headline.unit ? ` ${headline.unit}` : "";
  const comparison = (
    <>
      you <span className="text-text-secondary">{headline.you}</span>
      {headline.avg !== null ? (
        <>
          {" · "}avg <span className="text-text-secondary">{headline.avg}</span>
        </>
      ) : null}
      {unit}
    </>
  );
  const accessible =
    `${driver.label}: ${effectText(driver)}, ${formatPercent(driver.share)} of the total influence` +
    `${mixed ? " (mixed signal)" : ""}. You ${headline.you}` +
    `${headline.avg !== null ? `, average ${headline.avg}` : ""}${unit}.`;

  return (
    <li>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            tabIndex={0}
            aria-label={accessible}
            className={cn(
              ROW_GRID,
              "group/row items-center gap-y-1 rounded-lg px-2 py-2 -mx-2 outline-none transition-colors duration-150",
              "hover:bg-white/[0.025] focus-visible:bg-white/[0.035] focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-gold",
            )}
          >
            <div className="flex min-w-0 flex-col">
              <span className="flex min-w-0 items-baseline gap-1.5">
                <span className="truncate text-sm text-text">{driver.label}</span>
                {mixed ? <span className="shrink-0 text-[11px] text-text-muted">mixed signal</span> : null}
              </span>
              <span className="truncate text-xs tabular-nums text-text-muted">{comparison}</span>
            </div>
            <div className="relative order-last col-span-2 h-3 sm:order-none sm:col-span-1 sm:h-5">
              <span aria-hidden="true" className="absolute -inset-y-2 left-1/2 w-px -translate-x-1/2 bg-white/[0.09]" />
              {neutral ? (
                <span
                  aria-hidden="true"
                  className="absolute top-1/2 left-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
                  style={{ backgroundColor: CHART_COLORS.neutral }}
                />
              ) : (
                <motion.span
                  aria-hidden="true"
                  className={cn(
                    "absolute top-1/2 h-2.5 -translate-y-1/2 transition-[width,filter] duration-300 group-hover/row:brightness-125",
                    positive ? "left-1/2 rounded-r-[4px]" : "right-1/2 rounded-l-[4px]",
                  )}
                  style={{
                    width: `${width}%`,
                    backgroundColor: color,
                    transformOrigin: positive ? "left center" : "right center",
                  }}
                  initial={entrance ? { scaleX: 0 } : false}
                  animate={{ scaleX: 1 }}
                  transition={{
                    duration: MOTION.countUp,
                    ease: EASE_OUT,
                    delay: entrance ? Math.min(order, 12) * staggerStep(13) : 0,
                  }}
                />
              )}
            </div>
            <span
              className={cn(
                "text-right font-display text-sm font-semibold tabular-nums",
                neutral || mixed ? "text-text-secondary" : "text-text",
              )}
            >
              {neutral ? formatShare(0) : share}
            </span>
          </div>
        </TooltipTrigger>
        <TooltipContent side="top" align="start" className="max-w-80 text-left text-balance">
          <DriverTooltip driver={driver} color={color} icon={Icon} />
        </TooltipContent>
      </Tooltip>
    </li>
  );
}

function DriverTooltip({ driver, color, icon: Icon }: { driver: DriverDisplay; color: string; icon: LucideIcon }) {
  const { headline } = driver;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium text-text">{driver.label}</span>
        <span className="flex items-center gap-1 text-[11px] text-text-muted">
          <Icon className="size-3" aria-hidden="true" />
          {FEATURE_GROUP_LABELS[driver.group]}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <LegendKey color={color} mark="line" />
        <span className="font-display text-sm font-semibold tabular-nums text-text">
          {driver.neutral ? formatShare(0) : formatShare(signedShare(driver))}
        </span>
        <span className="text-text-secondary">of the influence · {effectText(driver)}</span>
      </div>
      <div className="text-text-secondary tabular-nums">
        You {headline.you}
        {headline.avg !== null ? ` · average ${headline.avg}` : ""}
        {headline.unit ? ` ${headline.unit}` : ""}
        {headline.relative !== null && headline.direction !== "even" && Math.abs(headline.relative) < 10
          ? ` (${headline.relative > 0 ? "+" : "−"}${formatPercent(Math.abs(headline.relative))})`
          : ""}
      </div>
      {driver.members.length > 1 ? (
        <ul className="flex flex-col gap-0.5 border-t border-border pt-1.5" aria-label="Model inputs in this stat">
          {driver.members.map((member) => (
            <li key={member.feature} className="flex items-baseline justify-between gap-3">
              <span className="text-text-secondary">{member.label}</span>
              <span className="font-medium tabular-nums text-text">{formatShare(member.signedShare)}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="text-text-muted">{explainDriver(driver)}</p>
    </div>
  );
}
