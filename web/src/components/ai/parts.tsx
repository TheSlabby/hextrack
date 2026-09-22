/** Small building blocks shared by the AI Score components. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { BrainCircuit, Check, Copy, RotateCw, Terminal } from "lucide-react";

import { GlowCard } from "@/components/common";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { CHART_COLORS } from "@/lib/chartTheme";

import { AiScoreExplainer } from "./AiScoreExplainer";

// --- legend -----------------------------------------------------------------------------

export interface LegendItem {
  label: string;
  color: string;
  /** Legend keys mirror the mark: a square for bars, a stroke for lines, a hairline for references. */
  mark: "bar" | "line" | "reference";
}

/** Chart legend: coloured keys beside text-token labels (text never wears the series colour). */
export function ChartLegend({ items, className }: { items: readonly LegendItem[]; className?: string }) {
  return (
    <ul className={cn("flex flex-wrap items-center gap-x-3.5 gap-y-1 text-xs text-text-secondary", className)}>
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 whitespace-nowrap">
          <LegendKey color={item.color} mark={item.mark} />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

export function LegendKey({ color, mark }: { color: string; mark: LegendItem["mark"] }) {
  if (mark === "bar") {
    return <span aria-hidden="true" className="size-2.5 shrink-0 rounded-[3px]" style={{ backgroundColor: color }} />;
  }
  if (mark === "line") {
    return <span aria-hidden="true" className="h-0.5 w-3.5 shrink-0 rounded-full" style={{ backgroundColor: color }} />;
  }
  return <span aria-hidden="true" className="h-px w-3.5 shrink-0" style={{ backgroundColor: CHART_COLORS.reference }} />;
}

// --- command chip -----------------------------------------------------------------------

/** A shell command in a mono chip with a copy button. */
export function CommandChip({ command, className }: { command: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div
      className={cn(
        "inline-flex max-w-full items-center gap-2 rounded-lg border border-cyan/25 bg-bg py-1 pr-1 pl-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]",
        className,
      )}
    >
      <span aria-hidden="true" className="font-mono text-[13px] text-cyan/70 select-none">
        $
      </span>
      <code className="min-w-0 truncate font-mono text-[13px] text-text">{command}</code>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={copy}
            aria-label={copied ? "Copied" : `Copy command: ${command}`}
            className="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-text-secondary transition-colors hover:bg-white/5 hover:text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold"
          >
            {copied ? <Check className="size-3.5 text-cyan" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
          </button>
        </TooltipTrigger>
        <TooltipContent>{copied ? "Copied" : "Copy"}</TooltipContent>
      </Tooltip>
      <span className="sr-only" aria-live="polite">
        {copied ? "Command copied" : ""}
      </span>
    </div>
  );
}

// --- model missing ----------------------------------------------------------------------

/** Designed state for "no AI model is trained yet" (the API answered 503 model_missing). */
export function ModelMissingState({ compact, className }: { compact?: boolean; className?: string }) {
  return (
    <GlowCard glow="cyan" className={cn("overflow-hidden", compact ? "p-5" : "p-6 sm:p-8", className)}>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 -top-28 mx-auto h-56 w-[32rem] max-w-full rounded-full bg-cyan/10 blur-3xl"
      />
      <div className="relative mx-auto flex max-w-xl flex-col items-center gap-4 text-center">
        <span className="flex size-14 items-center justify-center rounded-2xl border border-cyan/30 bg-cyan/10 text-cyan shadow-[var(--shadow-glow-cyan)]">
          <BrainCircuit className="size-7" aria-hidden="true" />
        </span>
        <div className="flex flex-col gap-1.5">
          <span className="label-caps text-cyan">AI Score</span>
          <h3 className="text-lg font-semibold text-text sm:text-xl">AI model not trained yet</h3>
          <p className="text-sm leading-relaxed text-text-secondary">
            Insights appear once a model has learned from the stored ranked games. Train one on the server:
          </p>
        </div>
        <CommandChip command="hextrack train --activate" />
        <ul className="flex flex-col items-center gap-2 text-xs leading-relaxed text-text-secondary">
          <li className="flex items-center gap-1.5">
            <RotateCw className="size-3.5 shrink-0 text-text-muted" aria-hidden="true" />
            Then restart the API and worker so they load it.
          </li>
          <li className="flex flex-wrap items-center justify-center gap-1.5">
            <Terminal className="size-3.5 shrink-0 text-text-muted" aria-hidden="true" />
            Score games already stored with
            <code className="rounded border border-border-strong bg-surface-2 px-1.5 py-px font-mono text-[11px] whitespace-nowrap text-text">
              hextrack model rescore
            </code>
          </li>
        </ul>
        <AiScoreExplainer />
      </div>
    </GlowCard>
  );
}

// --- inline stat ------------------------------------------------------------------------

/** Compact label + value pair used in chart headers (smaller than a StatTile). */
export function InlineStat({
  label,
  children,
  caption,
  className,
}: {
  label: string;
  children: ReactNode;
  caption?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <span className="label-caps truncate">{label}</span>
      <div className="flex min-w-0 items-center gap-2">{children}</div>
      {caption ? <span className="truncate text-xs text-text-muted">{caption}</span> : null}
    </div>
  );
}
