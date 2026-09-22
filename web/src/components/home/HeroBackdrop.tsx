import { useId } from "react";
import { motion, useReducedMotion } from "motion/react";

import { cn } from "@/lib/cn";

// Pointy-top honeycomb on a 1200x560 canvas (scaled with "slice" so it always covers).
const R = 26; // hex circumradius
const W = R * Math.sqrt(3); // hex width
const TILE_PATH = `M${W / 2} 0 L${W} ${R / 2} L${W} ${(3 * R) / 2} L${W / 2} ${2 * R} L0 ${(3 * R) / 2} L0 ${R / 2} Z M${W / 2} ${2 * R} L${W / 2} ${3 * R}`;

type Cell = { i: number; j: number; offset: boolean; tone: "gold" | "cyan"; delay: number };

/** Cells that softly light up. `offset` cells sit on the tile seams (the in-between row). */
const LIT_CELLS: readonly Cell[] = [
  { i: 4, j: 1, offset: false, tone: "gold", delay: 0 },
  { i: 7, j: 3, offset: true, tone: "gold", delay: 2.4 },
  { i: 9, j: 0, offset: false, tone: "cyan", delay: 5.1 },
  { i: 16, j: 1, offset: true, tone: "gold", delay: 1.2 },
  { i: 19, j: 3, offset: false, tone: "cyan", delay: 3.6 },
  { i: 22, j: 2, offset: true, tone: "gold", delay: 6.3 },
  { i: 24, j: 0, offset: false, tone: "gold", delay: 4.2 },
  { i: 3, j: 4, offset: true, tone: "cyan", delay: 7.0 },
  { i: 12, j: 5, offset: false, tone: "gold", delay: 2.0 },
  { i: 20, j: 5, offset: true, tone: "gold", delay: 5.7 },
];

function cellPath({ i, j, offset }: Cell): string {
  const cx = offset ? W * i : W / 2 + W * i;
  const cy = offset ? 2.5 * R + 3 * R * j : R + 3 * R * j;
  const pts = [
    [cx, cy - R],
    [cx + W / 2, cy - R / 2],
    [cx + W / 2, cy + R / 2],
    [cx, cy + R],
    [cx - W / 2, cy + R / 2],
    [cx - W / 2, cy - R / 2],
  ];
  return `M${pts.map(([x, y]) => `${x?.toFixed(1)} ${y?.toFixed(1)}`).join(" L")} Z`;
}

/** Token-based fill/stroke classes per lit-cell tone. */
const TONE_CLASS = {
  gold: "fill-gold stroke-gold-bright",
  cyan: "fill-cyan stroke-cyan",
} as const;

/**
 * Hero decoration: a faint hextech honeycomb that fades out from the centre, a few cells
 * that slowly light up, and two drifting glows (gold and cyan). Purely decorative; static
 * under prefers-reduced-motion.
 */
export function HeroBackdrop({ className }: { className?: string }) {
  const uid = useId().replace(/:/g, "");
  const reduced = useReducedMotion();

  return (
    <div
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute inset-0 -z-10 overflow-hidden [mask-image:radial-gradient(75%_80%_at_50%_38%,black_45%,transparent_100%)]",
        className,
      )}
    >
      <motion.div
        className="absolute -top-40 left-[4%] size-[560px] rounded-full bg-[radial-gradient(closest-side,rgba(200,170,110,0.11),transparent)]"
        animate={reduced ? undefined : { x: [0, 70, -30, 0], y: [0, 36, -18, 0] }}
        transition={{ duration: 28, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute top-4 -right-24 size-[520px] rounded-full bg-[radial-gradient(closest-side,rgba(10,200,185,0.08),transparent)]"
        animate={reduced ? undefined : { x: [0, -60, 24, 0], y: [0, -26, 40, 0] }}
        transition={{ duration: 34, repeat: Infinity, ease: "easeInOut" }}
      />
      <div className="absolute top-1/2 left-1/2 h-[280px] w-[720px] max-w-full -translate-x-1/2 -translate-y-1/3 rounded-full bg-[radial-gradient(closest-side,rgba(200,170,110,0.06),transparent)]" />

      <svg className="absolute inset-0 size-full" viewBox="0 0 1200 560" preserveAspectRatio="xMidYMid slice">
        <defs>
          <pattern id={`${uid}-hex`} width={W} height={3 * R} patternUnits="userSpaceOnUse">
            <path d={TILE_PATH} fill="none" className="stroke-gold" strokeOpacity={0.16} strokeWidth={1} />
          </pattern>
          <radialGradient id={`${uid}-fade`} cx="50%" cy="42%" r="62%">
            <stop offset="0%" stopColor="#fff" stopOpacity={0.9} />
            <stop offset="55%" stopColor="#fff" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#fff" stopOpacity={0} />
          </radialGradient>
          <mask id={`${uid}-mask`}>
            <rect width="1200" height="560" fill={`url(#${uid}-fade)`} />
          </mask>
        </defs>
        <g mask={`url(#${uid}-mask)`}>
          <rect width="1200" height="560" fill={`url(#${uid}-hex)`} />
          {LIT_CELLS.map((cell) => {
            return (
              <motion.path
                key={`${cell.i}-${cell.j}-${cell.offset ? "o" : "p"}`}
                d={cellPath(cell)}
                className={TONE_CLASS[cell.tone]}
                fillOpacity={0.09}
                strokeOpacity={0.35}
                strokeWidth={1}
                initial={{ opacity: reduced ? 0.45 : 0 }}
                animate={reduced ? { opacity: 0.45 } : { opacity: [0, 1, 0] }}
                transition={
                  reduced
                    ? { duration: 0 }
                    : { duration: 7, delay: cell.delay, repeat: Infinity, repeatDelay: 3, ease: "easeInOut" }
                }
              />
            );
          })}
        </g>
      </svg>
    </div>
  );
}
