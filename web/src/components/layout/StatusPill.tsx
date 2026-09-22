import { useHealth } from "@/api/queries";
import type { Health } from "@/api/types";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/format";

type Tone = "ok" | "warn" | "off" | "error";

interface PillState {
  tone: Tone;
  label: string;
}

const DOT: Record<Tone, string> = {
  ok: "bg-cyan shadow-[0_0_8px_rgba(10,200,185,0.8)]",
  warn: "bg-gold shadow-[0_0_8px_rgba(200,170,110,0.7)]",
  off: "bg-text-muted",
  error: "bg-loss shadow-[0_0_8px_rgba(255,93,108,0.7)]",
};

function pillState(health: Health | undefined, failed: boolean): PillState {
  if (failed) return { tone: "error", label: "API offline" };
  if (!health) return { tone: "off", label: "Connecting" };
  if (!health.db_ok) return { tone: "error", label: "Database down" };
  if (!health.riot.key_configured) return { tone: "warn", label: "Riot key missing" };
  if (health.riot.key_ok === false) return { tone: "warn", label: "Riot key rejected" };
  if (!health.model.loaded) return { tone: "off", label: "AI offline" };
  // The model version id belongs in the tooltip, not in the global nav.
  return { tone: "ok", label: "AI online" };
}

function Row({ label, value, tone }: { label: string; value: string; tone: Tone }) {
  return (
    <div className="flex items-center justify-between gap-6">
      <span className="text-text-secondary">{label}</span>
      <span className="flex items-center gap-1.5 font-medium text-text">
        <span aria-hidden="true" className={cn("size-1.5 rounded-full", DOT[tone])} />
        {value}
      </span>
    </div>
  );
}

/** Compact service status for the nav: AI model version, "AI offline" or "Riot key missing". */
export function StatusPill({ className }: { className?: string }) {
  const { data, isError, isPending } = useHealth();
  const state = pillState(data, isError);

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex h-7 items-center gap-1.5 rounded-full border border-border bg-surface-1/70 px-2.5 text-[11px] font-medium text-text-secondary transition-colors hover:border-border-strong hover:text-text",
            isPending && "animate-pulse-soft",
            className,
          )}
          aria-label={`Service status: ${state.label}`}
        >
          <span aria-hidden="true" className={cn("size-1.5 rounded-full", DOT[state.tone])} />
          <span className="max-w-32 truncate">{state.label}</span>
        </button>
      </TooltipTrigger>
      <TooltipContent align="end" className="w-64 max-w-none">
        {data ? (
          <div className="flex flex-col gap-1.5">
            <div className="label-caps mb-0.5">Service status · v{data.version}</div>
            <Row label="Database" value={data.db_ok ? "Connected" : "Unreachable"} tone={data.db_ok ? "ok" : "error"} />
            <Row
              label="Riot API"
              value={!data.riot.key_configured ? "Key missing" : data.riot.key_ok === false ? "Key rejected" : "Ready"}
              tone={!data.riot.key_configured || data.riot.key_ok === false ? "warn" : "ok"}
            />
            <Row
              label="AI model"
              value={data.model.loaded ? (data.model.version ?? "Loaded") : "Not trained"}
              tone={data.model.loaded ? "ok" : "off"}
            />
            <Row
              label="Poller"
              value={
                data.poller.running
                  ? data.poller.last_run_at
                    ? `Ran ${timeAgo(data.poller.last_run_at)}`
                    : "Running"
                  : "Stopped"
              }
              tone={data.poller.running ? (data.poller.last_error ? "warn" : "ok") : "off"}
            />
            {data.riot.last_error ? <p className="mt-1 text-[11px] text-text-muted">{data.riot.last_error}</p> : null}
          </div>
        ) : isError ? (
          "The HexTrack API is not responding."
        ) : (
          "Checking service status…"
        )}
      </TooltipContent>
    </Tooltip>
  );
}
