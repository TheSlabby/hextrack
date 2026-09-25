import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";

import type { SquadPlayer } from "@/api/types";
import { ProfileIcon } from "@/components/common/ProfileIcon";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { InGameDot } from "@/components/live/InGameDot";
import { useLivePuuids } from "@/components/live/useLivePuuids";
import { cn } from "@/lib/cn";
import { formatRiotId, summonerParams } from "@/lib/riotId";

export interface MatrixCellSpec {
  /** Full description of the cell for screen readers. */
  label: string;
  /** Visible content (short: the cell is ~52-64px wide). */
  content: ReactNode;
  /** "value": coloured by `fill`; "muted": below the sample threshold; "empty": no games; "self": the diagonal. */
  variant: "value" | "muted" | "empty" | "self";
  /** Background colour for "value" cells. */
  fill?: string;
}

export interface PlayerMatrixProps {
  players: readonly SquadPlayer[];
  labels: ReadonlyMap<string, string>;
  /** Table caption (screen readers). */
  caption: string;
  /** Off-diagonal cell: `row` read against `col`. */
  cell: (row: SquadPlayer, col: SquadPlayer) => MatrixCellSpec;
  /** Diagonal cell. */
  self: (player: SquadPlayer) => MatrixCellSpec;
  /** Tooltip body for a cell (`row === col` on the diagonal). */
  detail: (row: SquadPlayer, col: SquadPlayer) => ReactNode;
  className?: string;
}

type Mode = "hover" | "focus" | "pinned";

/** The cell whose tooltip is open, by player (so a filter change never points it at other players). */
interface ActiveCell {
  row: string;
  col: string;
  mode: Mode;
}

/**
 * For text beside a matrix (headers, legends, notes): it fills the card but adds nothing to
 * the card's intrinsic width, so the card is as wide as its table and prose wraps to fit.
 */
export const FIT_TABLE = "[contain:inline-size]";

const CELL_SIZE = "h-11 w-[52px] sm:h-12 sm:w-16";

/** Diagonal cells: a gold hairline and no fill, so they never read as a colour bin. */
export const SELF_CELL_CLASS = "bg-gold/[0.05] text-text-secondary ring-1 ring-gold/35 ring-inset";

const VARIANT: Readonly<Record<MatrixCellSpec["variant"], string>> = {
  value: "text-text hover:brightness-125",
  muted: "bg-white/[0.025] text-text-muted hover:bg-white/[0.06]",
  empty: "text-text-muted hover:bg-white/[0.04]",
  self: cn(SELF_CELL_CLASS, "hover:bg-gold/[0.1]"),
};

/**
 * Player-by-player grid: profile icons on both axes, one button per cell. The first column
 * sticks while the grid scrolls sideways inside its card (phones).
 *
 * One shared tooltip follows the pointer (mouse hover), keyboard focus (arrow keys move
 * between cells: a single tab stop) or a tap/click, which pins it until the next tap. Every
 * cell also carries its full reading in `aria-label`, so the tooltip never gates a value.
 */
export function PlayerMatrix({ players, labels, caption, cell, self, detail, className }: PlayerMatrixProps) {
  const live = useLivePuuids();
  const tableRef = useRef<HTMLTableElement>(null);
  const anchorRef = useRef<HTMLElement | null>(null);
  const [focusPos, setFocusPos] = useState<readonly [number, number]>([0, 0]);
  const [active, setActive] = useState<ActiveCell | null>(null);

  const count = players.length;
  const focusRow = Math.min(focusPos[0], count - 1);
  const focusCol = Math.min(focusPos[1], count - 1);
  const activeR = active ? players.findIndex((player) => player.puuid === active.row) : -1;
  const activeC = active ? players.findIndex((player) => player.puuid === active.col) : -1;
  const activeCell = active && activeR >= 0 && activeC >= 0 ? { r: activeR, c: activeC, mode: active.mode } : null;
  const activeRow = activeCell ? players[activeCell.r] : undefined;
  const activeCol = activeCell ? players[activeCell.c] : undefined;

  const show = (r: number, c: number, mode: Mode, element: HTMLElement) => {
    const row = players[r];
    const col = players[c];
    if (!row || !col) return;
    anchorRef.current = element;
    setActive({ row: row.puuid, col: col.puuid, mode });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, r: number, c: number) => {
    let nextRow = r;
    let nextCol = c;
    switch (event.key) {
      case "ArrowRight":
        nextCol = Math.min(count - 1, c + 1);
        break;
      case "ArrowLeft":
        nextCol = Math.max(0, c - 1);
        break;
      case "ArrowDown":
        nextRow = Math.min(count - 1, r + 1);
        break;
      case "ArrowUp":
        nextRow = Math.max(0, r - 1);
        break;
      case "Home":
        nextCol = 0;
        if (event.ctrlKey || event.metaKey) nextRow = 0;
        break;
      case "End":
        nextCol = count - 1;
        if (event.ctrlKey || event.metaKey) nextRow = count - 1;
        break;
      case "Escape":
        if (activeCell) {
          event.preventDefault();
          setActive(null);
        }
        return;
      default:
        return;
    }
    event.preventDefault();
    if (nextRow === r && nextCol === c) return;
    setFocusPos([nextRow, nextCol]);
    tableRef.current?.querySelector<HTMLButtonElement>(`[data-cell="${nextRow}-${nextCol}"]`)?.focus();
  };

  return (
    // `relative`: the sr-only labels inside the table are absolutely positioned, and must be
    // clipped by this scroller rather than widen the page on phones.
    <div className={cn("scrollbar-thin relative -mx-1 overflow-x-auto px-1 pb-1", className)}>
      <Popover
        open={activeCell !== null}
        onOpenChange={(open) => {
          if (!open) setActive(null);
        }}
      >
        <PopoverAnchor virtualRef={anchorRef} />
        <table ref={tableRef} className="border-separate border-spacing-0">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              <th scope="col" className="sticky left-0 z-10 bg-surface-1">
                <span className="sr-only">Player</span>
              </th>
              {players.map((player, c) => (
                <th key={player.puuid} scope="col" className="px-px pb-2 align-bottom font-normal">
                  <div
                    className={cn("mx-auto flex flex-col items-center gap-1", CELL_SIZE, "h-auto sm:h-auto")}
                    title={formatRiotId(player.game_name, player.tag_line)}
                  >
                    <ProfileIcon iconId={player.profile_icon_id} size="sm" alt="" />
                    <span
                      className={cn(
                        "w-full truncate text-center text-[11px] leading-4 transition-colors",
                        activeCell?.c === c ? "text-gold-bright" : "text-text-secondary",
                      )}
                    >
                      {labels.get(player.puuid) ?? player.game_name}
                    </span>
                    <InGameDot live={live.has(player.puuid)} className="-mt-0.5" />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {players.map((row, r) => (
              <tr key={row.puuid}>
                <th
                  scope="row"
                  className="sticky left-0 z-10 bg-surface-1 py-px pr-2 text-left font-normal shadow-[6px_0_8px_-8px_rgba(0,0,0,0.9)]"
                >
                  <Link
                    to="/summoner/$region/$riotId"
                    params={summonerParams(row.game_name, row.tag_line)}
                    title={formatRiotId(row.game_name, row.tag_line)}
                    className="focus-ring flex items-center gap-2 rounded-md py-1 pr-1 transition-colors hover:text-gold-bright"
                  >
                    <ProfileIcon iconId={row.profile_icon_id} size="xs" alt="" />
                    <span
                      className={cn(
                        "max-w-[64px] truncate text-xs font-medium sm:max-w-[132px] sm:text-[13px]",
                        activeCell?.r === r ? "text-gold-bright" : "text-text",
                      )}
                    >
                      {labels.get(row.puuid) ?? row.game_name}
                    </span>
                  </Link>
                </th>
                {players.map((col, c) => {
                  const spec = r === c ? self(row) : cell(row, col);
                  const isActive = activeCell?.r === r && activeCell.c === c;
                  return (
                    <td key={col.puuid} className="p-px">
                      <button
                        type="button"
                        data-cell={`${r}-${c}`}
                        tabIndex={r === focusRow && c === focusCol ? 0 : -1}
                        aria-label={spec.label}
                        className={cn(
                          "flex flex-col items-center justify-center rounded-md leading-tight tabular-nums transition-[filter,background-color,box-shadow] duration-150",
                          "outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-gold",
                          CELL_SIZE,
                          VARIANT[spec.variant],
                          isActive && "shadow-[inset_0_0_0_1px_rgba(255,255,255,0.55)]",
                        )}
                        style={spec.variant === "value" && spec.fill ? { backgroundColor: spec.fill } : undefined}
                        onPointerEnter={(event) => {
                          if (event.pointerType === "mouse") show(r, c, "hover", event.currentTarget);
                        }}
                        onPointerLeave={(event) => {
                          if (event.pointerType !== "mouse") return;
                          setActive((current) =>
                            current && current.mode === "hover" && current.row === row.puuid && current.col === col.puuid ? null : current,
                          );
                        }}
                        onFocus={(event) => {
                          setFocusPos([r, c]);
                          if (event.currentTarget.matches(":focus-visible")) show(r, c, "focus", event.currentTarget);
                        }}
                        onBlur={() =>
                          setActive((current) =>
                            current && current.mode === "focus" && current.row === row.puuid && current.col === col.puuid ? null : current,
                          )
                        }
                        onClick={(event) => {
                          if (activeCell?.mode === "pinned" && isActive) setActive(null);
                          else show(r, c, "pinned", event.currentTarget);
                        }}
                        onKeyDown={(event) => onKeyDown(event, r, c)}
                      >
                        {spec.content}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <PopoverContent
          side="top"
          sideOffset={8}
          collisionPadding={12}
          hideWhenDetached
          onOpenAutoFocus={(event) => event.preventDefault()}
          onCloseAutoFocus={(event) => event.preventDefault()}
          onInteractOutside={(event) => {
            // Cells manage the tooltip themselves (hover, focus, tap to pin / unpin).
            if (event.target instanceof Node && tableRef.current?.contains(event.target)) event.preventDefault();
          }}
          className="pointer-events-none w-64 rounded-lg p-3 text-xs"
        >
          {activeRow && activeCol ? detail(activeRow, activeCol) : null}
        </PopoverContent>
      </Popover>
    </div>
  );
}
