/**
 * Best time to play: a 7 x 24 heatmap of win rate by local weekday and hour of game start
 * (the viewer's time zone), the best and worst 3-hour windows, and compact by-day / by-hour
 * summaries on phones.
 */
import { useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { CalendarClock } from "lucide-react";

import { browserTimeZone, useScheduleInsights } from "@/api/queries";
import type { ScheduleCell, ScheduleDay, ScheduleHour, ScheduleInsights, ScheduleWindow } from "@/api/types";
import { EmptyState, ErrorState, GlowCard, SectionHeader } from "@/components/common";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { formatPercent, formatRecord, plural } from "@/lib/format";

import {
  WINRATE_BINS,
  aiPoints,
  dayLong,
  dayShort,
  gamesPhrase,
  hourRange,
  hourTick,
  markScale,
  timeZoneAbbreviation,
  windowLabel,
  winrateColor,
  type TrendsFilters,
} from "./model";
import { Refetching } from "./parts";

const DAYS = [0, 1, 2, 3, 4, 5, 6] as const;
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
/** Hour labels above the heatmap and below the hour strip. */
const HEAT_TICKS = new Set([0, 3, 6, 9, 12, 15, 18, 21]);
/** Hour labels under each 12-hour row of the phone strip. */
const STRIP_TICKS = new Set([0, 3, 6, 9, 12, 15, 18, 21]);
/** The phone strip is two rows of 12 hours (AM, PM), so each button is ~24px wide, not 11px. */
const STRIP_HALVES = [HOURS.slice(0, 12), HOURS.slice(12)] as const;

/** Muted mark for a sample below the minimum, and the faint well of an empty cell. */
const SMALL_SAMPLE_BORDER = "rgba(255, 255, 255, 0.22)";
const EMPTY_WELL = "rgba(255, 255, 255, 0.025)";

/** What the readout describes: one heatmap cell (desktop) or one hour of the phone strip. */
type Focus = { kind: "cell"; dow: number; hour: number } | { kind: "hour"; hour: number };

export interface ScheduleCardProps {
  puuid: string;
  filters: TrendsFilters;
}

export function ScheduleCard({ puuid, filters }: ScheduleCardProps) {
  const [tz] = useState(browserTimeZone);
  const query = useScheduleInsights(puuid, { ...filters, tz });
  const data = query.data;
  const games = data ? data.by_dow.reduce((sum, day) => sum + day.games, 0) : 0;
  const zone = timeZoneAbbreviation(data?.tz ?? tz);

  let body: ReactNode;
  if (query.isPending) {
    body = <ScheduleSkeleton />;
  } else if (query.isError) {
    body = <ErrorState compact error={query.error} title="Couldn't load the schedule" onRetry={() => void query.refetch()} />;
  } else if (!data || games === 0) {
    body = (
      <EmptyState
        compact
        icon={CalendarClock}
        title="No games to place yet"
        description={`No ${gamesPhrase(filters)} stored for this player.`}
      />
    );
  } else {
    body = (
      <Refetching active={query.isPlaceholderData}>
        <ScheduleBody data={data} />
      </Refetching>
    );
  }

  return (
    <GlowCard className="flex flex-col gap-4 p-4 sm:p-5">
      <SectionHeader
        eyebrow="Best time to play"
        title="Win rate by day and hour"
        icon={CalendarClock}
        description={
          data && games > 0
            ? `${plural(games, "game")} by start time, in your time zone (${zone}).`
            : `Game start times in your time zone (${zone}).`
        }
      />
      {body}
    </GlowCard>
  );
}

// --- body -------------------------------------------------------------------------------

function ScheduleBody({ data }: { data: ScheduleInsights }) {
  const [focus, setFocus] = useState<Focus | null>(null);
  const cells = useMemo(() => new Map(data.cells.map((cell) => [cellKey(cell.dow, cell.hour), cell])), [data.cells]);
  const maxGames = useMemo(() => Math.max(1, ...data.cells.map((cell) => cell.games)), [data.cells]);

  return (
    <div className="flex flex-col gap-4">
      <WindowCallouts best={data.best_window} worst={data.worst_window} minGames={data.min_games} />

      <div className="hidden flex-col gap-2 sm:flex">
        <Heatmap
          cells={cells}
          maxGames={maxGames}
          minGames={data.min_games}
          best={data.best_window}
          worst={data.worst_window}
          focus={focus?.kind === "cell" ? focus : null}
          onFocus={setFocus}
        />
      </div>

      <div className="flex flex-col gap-4 sm:hidden">
        <DayList days={data.by_dow} minGames={data.min_games} />
        <HourStrip hours={data.by_hour} minGames={data.min_games} focus={focus?.kind === "hour" ? focus.hour : null} onFocus={setFocus} />
      </div>

      <Readout focus={focus} data={data} cells={cells} />
      <HeatLegend minGames={data.min_games} />
      <ScheduleSummary data={data} />
    </div>
  );
}

function cellKey(dow: number, hour: number): string {
  return `${dow}-${hour}`;
}

// --- best / worst windows ---------------------------------------------------------------

function WindowCallouts({
  best,
  worst,
  minGames,
}: {
  best: ScheduleWindow | null;
  worst: ScheduleWindow | null;
  minGames: number;
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <WindowPanel
        label="Best 3 hours"
        window={best}
        minGames={minGames}
        ring="border-gold"
        empty={`No 3-hour window has ${minGames}+ games yet`}
      />
      <WindowPanel
        label="Worst 3 hours"
        window={worst}
        minGames={minGames}
        ring="border-text-secondary"
        empty={best ? `No weaker window with ${minGames}+ games` : `No 3-hour window has ${minGames}+ games yet`}
      />
    </div>
  );
}

/** A window under this many times the API's cell minimum is flagged "small sample". */
const WINDOW_SOLID_FACTOR = 2;

function WindowPanel({
  label,
  window,
  minGames,
  ring,
  empty,
}: {
  label: string;
  window: ScheduleWindow | null;
  minGames: number;
  ring: string;
  empty: string;
}) {
  const small = window !== null && window.games < WINDOW_SOLID_FACTOR * minGames;
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-xl border border-border bg-surface-2/50 p-3">
      <span className="label-caps flex items-center gap-1.5">
        <span aria-hidden="true" className={cn("hidden size-2.5 rounded-[3px] border-2 sm:inline-block", ring)} />
        {label}
      </span>
      {window ? (
        <>
          <span className="font-display text-lg leading-7 font-semibold text-text sm:text-xl">{windowLabel(window)}</span>
          <span className="text-xs text-text-muted tabular-nums">
            <span className="font-semibold text-text-secondary">{formatPercent(window.winrate)}</span> win rate ·{" "}
            {plural(window.games, "game")}
            {small ? <span className="text-text-muted"> · small sample</span> : null}
          </span>
        </>
      ) : (
        <span className="text-sm text-text-secondary">{empty}</span>
      )}
    </div>
  );
}

// --- heatmap ----------------------------------------------------------------------------

const GRID_COLUMNS = "2.25rem repeat(24, minmax(0, 1fr))";

function Heatmap({
  cells,
  maxGames,
  minGames,
  best,
  worst,
  focus,
  onFocus,
}: {
  cells: Map<string, ScheduleCell>;
  maxGames: number;
  minGames: number;
  best: ScheduleWindow | null;
  worst: ScheduleWindow | null;
  focus: { dow: number; hour: number } | null;
  onFocus: (focus: Focus | null) => void;
}) {
  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    const deltas: Record<string, [number, number]> = {
      ArrowUp: [-1, 0],
      ArrowDown: [1, 0],
      ArrowLeft: [0, -1],
      ArrowRight: [0, 1],
    };
    if (event.key === "Escape") {
      onFocus(null);
      return;
    }
    const delta = deltas[event.key];
    if (!delta) return;
    event.preventDefault();
    const start = focus ?? (best ? { dow: best.dow, hour: best.start_hour } : { dow: 0, hour: 18 });
    const dow = Math.min(6, Math.max(0, start.dow + (focus ? delta[0] : 0)));
    const hour = Math.min(23, Math.max(0, start.hour + (focus ? delta[1] : 0)));
    onFocus({ kind: "cell", dow, hour });
  };

  return (
    <div
      role="group"
      aria-label="Win rate heatmap by weekday and hour. Use the arrow keys to read each hour."
      tabIndex={0}
      onKeyDown={move}
      onPointerLeave={(event) => {
        if (event.pointerType === "mouse") onFocus(null);
      }}
      className="grid gap-[2px] rounded-lg outline-offset-4 select-none focus-visible:outline-2 focus-visible:outline-gold"
      style={{ gridTemplateColumns: GRID_COLUMNS }}
    >
      {HOURS.map((hour) => (
        <span
          key={`h${hour}`}
          aria-hidden="true"
          className="pb-1 text-[11px] leading-4 whitespace-nowrap text-text-muted tabular-nums"
          style={{ gridRow: 1, gridColumn: hour + 2 }}
        >
          {HEAT_TICKS.has(hour) ? hourTick(hour) : ""}
        </span>
      ))}
      {DAYS.map((dow) => (
        <span
          key={`d${dow}`}
          aria-hidden="true"
          className="flex items-center text-[11px] font-medium text-text-secondary"
          style={{ gridRow: dow + 2, gridColumn: 1 }}
        >
          {dayShort(dow)}
        </span>
      ))}
      {DAYS.flatMap((dow) =>
        HOURS.map((hour) => {
          const cell = cells.get(cellKey(dow, hour));
          const active = focus?.dow === dow && focus.hour === hour;
          return (
            <div
              key={cellKey(dow, hour)}
              className={cn(
                "relative flex aspect-square items-center justify-center rounded-[4px]",
                active && "ring-1 ring-text",
              )}
              style={{ gridRow: dow + 2, gridColumn: hour + 2, backgroundColor: EMPTY_WELL }}
              onPointerEnter={() => onFocus({ kind: "cell", dow, hour })}
              onClick={() => onFocus({ kind: "cell", dow, hour })}
            >
              {cell ? <HeatMark cell={cell} maxGames={maxGames} minGames={minGames} /> : null}
            </div>
          );
        }),
      )}
      {best ? <WindowOutline window={best} className="border-gold" /> : null}
      {worst ? <WindowOutline window={worst} className="border-text-secondary" /> : null}
    </div>
  );
}

function HeatMark({ cell, maxGames, minGames }: { cell: ScheduleCell; maxGames: number; minGames: number }) {
  const size = `${Math.round(markScale(cell.games, maxGames) * 100)}%`;
  const small = cell.games < minGames;
  return (
    <span
      aria-hidden="true"
      className="block rounded-[3px]"
      style={
        small
          ? { width: size, height: size, border: `1.5px solid ${SMALL_SAMPLE_BORDER}` }
          : { width: size, height: size, backgroundColor: winrateColor(cell.wins / cell.games) }
      }
    />
  );
}

function WindowOutline({ window, className }: { window: ScheduleWindow; className: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("pointer-events-none -m-[2px] rounded-[6px] border-2", className)}
      style={{ gridRow: window.dow + 2, gridColumn: `${window.start_hour + 2} / span ${window.end_hour - window.start_hour}` }}
    />
  );
}

// --- phone summaries --------------------------------------------------------------------

function DayList({ days, minGames }: { days: readonly ScheduleDay[]; minGames: number }) {
  return (
    <section aria-label="Win rate by day of week" className="flex flex-col gap-1.5">
      <h3 className="label-caps">By day</h3>
      <ul className="flex flex-col gap-1">
        {days.map((day) => {
          const small = day.games < minGames;
          return (
            <li key={day.dow} className="grid grid-cols-[2.25rem_minmax(0,1fr)_2.75rem_4.5rem] items-center gap-2 text-xs tabular-nums">
              <span className="font-medium text-text-secondary">{dayShort(day.dow)}</span>
              <span className="relative h-2 overflow-hidden rounded-full bg-white/[0.05]">
                {day.games > 0 ? (
                  <span
                    className="absolute inset-y-0 left-0 rounded-full"
                    style={{
                      width: `${Math.max(2, day.winrate * 100)}%`,
                      backgroundColor: small ? SMALL_SAMPLE_BORDER : winrateColor(day.winrate),
                    }}
                  />
                ) : null}
                <span aria-hidden="true" className="absolute inset-y-0 left-1/2 w-px bg-white/25" />
              </span>
              <span className={cn("text-right font-semibold", small ? "text-text-muted" : "text-text")}>
                {day.games > 0 ? formatPercent(day.winrate) : "–"}
              </span>
              <span className="text-right text-text-muted">{plural(day.games, "game")}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function HourStrip({
  hours,
  minGames,
  focus,
  onFocus,
}: {
  hours: readonly ScheduleHour[];
  minGames: number;
  focus: number | null;
  onFocus: (focus: Focus | null) => void;
}) {
  return (
    <section aria-label="Win rate by hour of day" className="flex flex-col gap-1.5">
      <h3 className="label-caps">By hour · tap for details</h3>
      {STRIP_HALVES.map((half) => (
        <div key={half[0]} className="flex flex-col gap-1">
          <div className="grid grid-cols-[repeat(12,minmax(0,1fr))] gap-[2px]">
            {half.map((h) => {
              const hour = hours.find((entry) => entry.hour === h) ?? { hour: h, games: 0, wins: 0, winrate: 0, avg_ai_score: null };
              const small = hour.games < minGames;
              return (
                <button
                  key={h}
                  type="button"
                  aria-label={hourAria(hour, minGames)}
                  aria-pressed={focus === h}
                  onClick={() => onFocus(focus === h ? null : { kind: "hour", hour: h })}
                  className={cn(
                    "h-8 min-w-6 rounded-[3px] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-gold",
                    focus === h && "ring-1 ring-text",
                  )}
                  style={
                    hour.games === 0
                      ? { backgroundColor: EMPTY_WELL }
                      : small
                        ? { boxShadow: `inset 0 0 0 1.5px ${SMALL_SAMPLE_BORDER}` }
                        : { backgroundColor: winrateColor(hour.winrate) }
                  }
                />
              );
            })}
          </div>
          <div aria-hidden="true" className="grid grid-cols-[repeat(12,minmax(0,1fr))] text-[11px] text-text-muted tabular-nums">
            {half.map((h) => (
              <span key={h} className="whitespace-nowrap">
                {STRIP_TICKS.has(h) ? hourTick(h) : ""}
              </span>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

function hourAria(hour: ScheduleHour, minGames: number): string {
  const range = hourRange(hour.hour, hour.hour + 1);
  if (hour.games === 0) return `${range}: no games`;
  return `${range}: ${formatPercent(hour.winrate)} win rate over ${plural(hour.games, "game")}${hour.games < minGames ? ", small sample" : ""}`;
}

// --- readout, legend, summary -----------------------------------------------------------

function Readout({ focus, data, cells }: { focus: Focus | null; data: ScheduleInsights; cells: Map<string, ScheduleCell> }) {
  let title: string;
  let record: { games: number; wins: number; ai: number | null } | null = null;
  if (!focus) {
    title = "";
  } else if (focus.kind === "cell") {
    title = `${dayLong(focus.dow)}, ${hourRange(focus.hour, focus.hour + 1)}`;
    const cell = cells.get(cellKey(focus.dow, focus.hour));
    record = cell ? { games: cell.games, wins: cell.wins, ai: aiPoints(cell.avg_ai_score) } : { games: 0, wins: 0, ai: null };
  } else {
    const hour = data.by_hour[focus.hour];
    title = `Any day, ${hourRange(focus.hour, focus.hour + 1)}`;
    record = hour ? { games: hour.games, wins: hour.wins, ai: aiPoints(hour.avg_ai_score) } : null;
  }

  return (
    <div
      className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-0.5 rounded-xl border border-border bg-surface-2/50 px-3 py-2 text-sm"
      aria-live="polite"
    >
      {focus && record ? (
        <>
          <span className="font-medium text-text">{title}</span>
          {record.games === 0 ? (
            <span className="text-text-muted">No games</span>
          ) : (
            <span className="text-text-secondary tabular-nums">
              <span className="font-semibold text-text">{formatPercent(record.wins / record.games)}</span> win rate ·{" "}
              {formatRecord(record.wins, record.games - record.wins)} · {record.ai !== null ? `avg AI ${record.ai}` : "not scored"}
              {record.games < data.min_games ? <span className="text-text-muted"> · small sample</span> : null}
            </span>
          )}
        </>
      ) : (
        <span className="text-text-muted">
          <span className="hidden sm:inline">Hover a cell (or focus the grid and use the arrow keys) for its record.</span>
          <span className="sm:hidden">Tap an hour for its record.</span>
        </span>
      )}
    </div>
  );
}

function HeatLegend({ minGames }: { minGames: number }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-text-secondary">
      <span className="flex items-center gap-1.5">
        <span className="text-text-muted">Win rate</span>
        <ul className="flex items-center gap-[2px]" aria-label="Win rate colours">
          {WINRATE_BINS.map((bin) => (
            <li key={bin.label} className="flex flex-col items-center" title={bin.description}>
              <span aria-hidden="true" className="h-2.5 w-7 rounded-[3px]" style={{ backgroundColor: bin.color }} />
              <span className="sr-only">{bin.description}</span>
            </li>
          ))}
        </ul>
        <span className="tabular-nums text-text-muted">
          {WINRATE_BINS[0]?.label} to {WINRATE_BINS[WINRATE_BINS.length - 1]?.label}
        </span>
      </span>
      <span className="hidden items-center gap-1.5 sm:flex">
        <span aria-hidden="true" className="flex items-end gap-0.5">
          <span className="size-1.5 rounded-[2px] bg-text-muted" />
          <span className="size-2.5 rounded-[2px] bg-text-muted" />
        </span>
        Bigger = more games
      </span>
      <span className="flex items-center gap-1.5">
        <span aria-hidden="true" className="size-2.5 rounded-[3px]" style={{ border: `1.5px solid ${SMALL_SAMPLE_BORDER}` }} />
        Under {minGames} games
      </span>
    </div>
  );
}

/** Screen-reader summary of what the heatmap shows. */
function ScheduleSummary({ data }: { data: ScheduleInsights }) {
  const days = data.by_dow
    .filter((day) => day.games > 0)
    .map((day) => `${dayLong(day.dow)} ${formatPercent(day.winrate)} over ${plural(day.games, "game")}`)
    .join("; ");
  return (
    <p className="sr-only">
      {data.best_window
        ? `Best window: ${windowLabel(data.best_window)}, ${formatPercent(data.best_window.winrate)} over ${plural(data.best_window.games, "game")}.`
        : ""}{" "}
      {data.worst_window
        ? `Worst window: ${windowLabel(data.worst_window)}, ${formatPercent(data.worst_window.winrate)} over ${plural(data.worst_window.games, "game")}.`
        : ""}{" "}
      By day: {days}.
    </p>
  );
}

// --- loading ----------------------------------------------------------------------------

function ScheduleSkeleton() {
  return (
    <div className="flex flex-col gap-4" role="status" aria-label="Loading the schedule">
      <div className="grid grid-cols-2 gap-2">
        <Skeleton className="h-[5.25rem] rounded-xl" />
        <Skeleton className="h-[5.25rem] rounded-xl" />
      </div>
      <div className="hidden gap-[2px] sm:grid" style={{ gridTemplateColumns: GRID_COLUMNS }}>
        {DAYS.flatMap((dow) => [
          <Skeleton key={`l${dow}`} className="h-3 w-7 self-center" />,
          ...HOURS.map((hour) => <Skeleton key={`${dow}-${hour}`} className="aspect-square rounded-[4px] opacity-60" />),
        ])}
      </div>
      <div className="flex flex-col gap-1.5 sm:hidden">
        {DAYS.map((dow) => (
          <Skeleton key={dow} className="h-4 w-full" />
        ))}
      </div>
      <Skeleton className="h-11 rounded-xl" />
    </div>
  );
}
