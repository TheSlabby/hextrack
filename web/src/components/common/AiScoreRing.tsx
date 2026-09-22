import { useId, useLayoutEffect, useRef } from "react";
import { animate as animateValue } from "motion/react";

import { cn } from "@/lib/cn";
import { formatSigned } from "@/lib/format";
import { EASE_OUT, isInViewport, MOTION, useEntranceMotion } from "@/lib/motion";
import { averageOffset, gradeForRate, toScore100 } from "@/lib/score";

export interface AiScoreRingProps {
  /** API score 0..1, or null when unavailable. */
  score: number | null | undefined;
  /**
   * "game" (default): one game's score, coloured and captioned by its grade. "average": a mean
   * over many games, drawn in the AI accent with its distance from a coin flip, never graded
   * (averages follow win rate closely, see lib/score.ts).
   */
  kind?: "game" | "average";
  /** Diameter in px. */
  size?: number;
  thickness?: number;
  /** Caption under the number. */
  label?: string;
  /** Show the grade (or, for averages, the offset from 50) under the number. */
  showGrade?: boolean;
  /**
   * Sweep the arc and count up on first paint (default). Pass false for secondary rings so
   * only one gauge animates per view.
   */
  animate?: boolean;
  className?: string;
}

/** Approximate advance of one character of the text-xs bold grade caption, in px. */
const CAPTION_CHAR_PX = 7;
/** Space kept between the caption and the inside edge of the ring, per side, in px. */
const CAPTION_INSET_PX = 8;

const AVERAGE_COLOR = "#0ac8b9";
const AVERAGE_COLOR_DEEP = "#0a7b74";
const EMPTY_COLOR = "#5f6b82";

/** Circular gauge for an AI Score (0-100). The arc and the number land together in 0.45 s. */
export function AiScoreRing({
  score,
  kind = "game",
  size = 128,
  thickness,
  label = "AI Score",
  showGrade = true,
  animate = true,
  className,
}: AiScoreRingProps) {
  const uid = useId().replace(/:/g, "");
  const entrance = useEntranceMotion();
  const rootRef = useRef<HTMLDivElement>(null);
  const glowRef = useRef<SVGCircleElement>(null);
  const arcRef = useRef<SVGCircleElement>(null);
  const numberRef = useRef<HTMLSpanElement>(null);
  const shown = useRef<number | null>(null);
  const settled = useRef(false);

  const stroke = thickness ?? Math.max(6, Math.round(size / 14));
  const r = (size - stroke) / 2 - 2;
  const c = size / 2;
  const circumference = 2 * Math.PI * r;
  const has = score !== null && score !== undefined;
  const value = has ? toScore100(score) : 0;
  const average = kind === "average";
  const grade = has && !average ? gradeForRate(score) : null;
  const offset = has && average ? averageOffset(score) : null;
  const color = !has ? EMPTY_COLOR : average ? AVERAGE_COLOR : (grade?.color ?? EMPTY_COLOR);
  const numberSize = Math.round(size * 0.3);
  // "C · Leaning loss" only when it clears the inside of the ring; otherwise just the letter.
  const fullCaption = grade ? `${grade.grade} · ${grade.label}` : "";
  const innerWidth = 2 * r - stroke - 2 * CAPTION_INSET_PX;
  const captionFits = size >= 112 && fullCaption.length * CAPTION_CHAR_PX <= innerWidth;
  const finalLength = (value / 100) * circumference;

  useLayoutEffect(() => {
    const number = numberRef.current;
    if (!has || !number) return;
    const arcs = [glowRef.current, arcRef.current];
    const paint = (latest: number) => {
      shown.current = latest;
      number.textContent = String(Math.round(latest));
      const length = (latest / 100) * circumference;
      for (const arc of arcs) {
        arc?.setAttribute("stroke-dasharray", `${length} ${circumference}`);
        arc?.setAttribute("visibility", length < 0.5 ? "hidden" : "visible");
      }
    };
    const root = rootRef.current;
    const start =
      !settled.current && animate && entrance && root !== null && (shown.current !== null || isInViewport(root));
    if (!start) {
      settled.current = true;
      paint(value);
      return;
    }
    const from = shown.current ?? 0;
    paint(from);
    const controls = animateValue(from, value, {
      duration: MOTION.countUp,
      ease: EASE_OUT,
      onUpdate: paint,
      onComplete: () => {
        settled.current = true;
      },
    });
    return () => controls.stop();
  }, [has, value, circumference, animate, entrance]);

  const ariaLabel = !has
    ? `${label}: not available`
    : average
      ? `${label}: ${value} of 100, ${formatSigned(offset ?? 0)} versus a coin flip`
      : `${label}: ${value} of 100, grade ${grade?.grade}`;

  return (
    <div
      ref={rootRef}
      className={cn("relative inline-flex shrink-0 items-center justify-center", className)}
      style={{ width: size, height: size }}
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={has ? value : undefined}
      aria-label={ariaLabel}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden="true">
        <defs>
          <linearGradient id={`${uid}-arc`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={average ? AVERAGE_COLOR_DEEP : color} stopOpacity={average ? 1 : 0.65} />
            <stop offset="100%" stopColor={color} />
          </linearGradient>
          <filter id={`${uid}-glow`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation={stroke * 0.6} />
          </filter>
        </defs>
        <circle cx={c} cy={c} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={stroke} />
        {has ? (
          <>
            <circle
              ref={glowRef}
              cx={c}
              cy={c}
              r={r}
              fill="none"
              stroke={color}
              strokeOpacity={average ? 0.25 : 0.35}
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={`${finalLength} ${circumference}`}
              visibility={finalLength < 0.5 ? "hidden" : "visible"}
              filter={`url(#${uid}-glow)`}
            />
            <circle
              ref={arcRef}
              cx={c}
              cy={c}
              r={r}
              fill="none"
              stroke={`url(#${uid}-arc)`}
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={`${finalLength} ${circumference}`}
              visibility={finalLength < 0.5 ? "hidden" : "visible"}
            />
          </>
        ) : null}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        <span className="font-display leading-none font-semibold tabular-nums text-text" style={{ fontSize: numberSize }}>
          {/* Painted by the layout effect (count-up), so React never owns these digits. */}
          {has ? <span ref={numberRef} /> : "–"}
        </span>
        {showGrade && grade ? (
          <span
            className={cn("mt-1 font-display font-bold tracking-wide", size >= 112 ? "text-xs" : "text-[10px]", grade.textClass)}
          >
            {captionFits ? fullCaption : grade.grade}
          </span>
        ) : null}
        {showGrade && offset !== null ? (
          <span
            className={cn(
              "mt-1 font-semibold tabular-nums",
              size >= 112 ? "text-xs" : "text-[10px]",
              offset > 0 ? "text-score-a" : offset < 0 ? "text-loss" : "text-text-muted",
            )}
          >
            {offset === 0 ? "±0" : formatSigned(offset)}
            {size >= 112 ? " vs 50" : null}
          </span>
        ) : null}
        {size >= 96 ? <span className="label-caps mt-0.5 text-[10px]">{label}</span> : null}
      </div>
    </div>
  );
}
