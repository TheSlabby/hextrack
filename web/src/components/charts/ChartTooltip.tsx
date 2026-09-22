import type { ReactNode } from "react";
import type { TooltipContentProps, TooltipPayloadEntry } from "recharts";

import { cn } from "@/lib/cn";

type Value = number | string | ReadonlyArray<number | string>;
type Name = number | string;

export interface ChartTooltipProps extends Partial<Omit<TooltipContentProps<Value, Name>, "labelFormatter">> {
  /** Heading above the rows (defaults to the x label). */
  labelFormatter?: (label: unknown, payload: ReadonlyArray<TooltipPayloadEntry<Value, Name>>) => ReactNode;
  /** Format each row's value (the strong element). */
  valueFormatter?: (value: Value | undefined, entry: TooltipPayloadEntry<Value, Name>) => ReactNode;
  /** Format each row's series name (the secondary element). */
  nameFormatter?: (name: Name | undefined, entry: TooltipPayloadEntry<Value, Name>) => ReactNode;
  /** Replace the rows entirely with custom content built from the hovered datum. */
  renderBody?: (datum: unknown, payload: ReadonlyArray<TooltipPayloadEntry<Value, Name>>) => ReactNode;
  /** Extra line under the rows (e.g. "Click to open match"). */
  footer?: ReactNode;
  className?: string;
}

/**
 * The one tooltip every Recharts chart uses:
 * `<Tooltip content={<ChartTooltip valueFormatter={...} />} {...tooltipProps} />`.
 *
 * Surface-2 card with a border; values lead (strong), series names follow (secondary),
 * and each row is keyed by a short stroke of the series colour, not a filled box.
 */
export function ChartTooltip({
  active,
  payload,
  label,
  labelFormatter,
  valueFormatter,
  nameFormatter,
  renderBody,
  footer,
  className,
}: ChartTooltipProps) {
  const rows = (payload ?? []).filter((entry) => !entry.hide && entry.type !== "none");
  if (!active || rows.length === 0) return null;
  const datum: unknown = rows[0]?.payload;
  const heading = labelFormatter ? labelFormatter(label, rows) : label;

  return (
    <div
      className={cn(
        "surface-raised pointer-events-none min-w-36 rounded-lg px-3 py-2.5 text-xs text-text",
        className,
      )}
    >
      {heading !== undefined && heading !== null && heading !== "" ? (
        <div className="mb-1.5 font-medium text-text-secondary">{heading as ReactNode}</div>
      ) : null}
      {renderBody ? (
        renderBody(datum, rows)
      ) : (
        <ul className="flex flex-col gap-1">
          {rows.map((entry, index) => {
            const color = entry.color ?? entry.stroke ?? entry.fill ?? "currentColor";
            return (
              <li key={`${String(entry.dataKey ?? entry.name ?? index)}`} className="flex items-center gap-2">
                <span aria-hidden="true" className="h-0.5 w-3 shrink-0 rounded-full" style={{ backgroundColor: color }} />
                <span className="font-display text-sm font-semibold tabular-nums text-text">
                  {valueFormatter ? valueFormatter(entry.value, entry) : formatDefault(entry.value)}
                </span>
                <span className="text-text-secondary">
                  {nameFormatter ? nameFormatter(entry.name, entry) : (entry.name as ReactNode)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {footer ? <div className="mt-2 border-t border-border pt-1.5 text-[11px] text-text-muted">{footer}</div> : null}
    </div>
  );
}

function formatDefault(value: Value | undefined): ReactNode {
  if (value === undefined) return "–";
  if (typeof value === "number") return Number.isInteger(value) ? value : value.toFixed(2);
  if (Array.isArray(value)) return value.join(" – ");
  return value as ReactNode;
}
