/**
 * Motion timing and the "first paint only" rule (see web/DESIGN.md → Motion).
 *
 * Every entrance settles within ~600 ms of its data arriving: 0.26 s fades, a 30 ms stagger
 * compressed so the last item starts by 0.15 s, 0.45 s count-ups and gauges, 350 ms charts.
 *
 * Sections that re-mount while the page stays open (Radix tabs unmount inactive panels) must
 * not replay their entrance. A page wraps itself in <MotionMemory> and each re-mountable part
 * in <AnimateOnce id="...">: the first mount animates, later mounts render settled. Motion
 * primitives (Stagger, Reveal, CountUp, AiScoreRing, charts via useChartAnimation) read
 * `useEntranceMotion()`, which is also false under prefers-reduced-motion.
 */
import { createContext, useContext, useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";

/** Expo-out: fast start, gentle landing. */
export const EASE_OUT = [0.16, 1, 0.3, 1] as const;

export const MOTION = {
  /** Fade + 8px slide of one item, seconds. */
  duration: 0.26,
  /** Delay between staggered items, seconds. */
  stagger: 0.03,
  /** The last staggered item starts at most this long after the first, seconds. */
  maxStaggerSpan: 0.15,
  /** Count-ups and gauge sweeps, seconds. */
  countUp: 0.45,
  /** Recharts series, milliseconds. */
  chartMs: 350,
} as const;

/** Seconds between items when `count` items share one stagger (compressed to fit the span). */
export function staggerStep(count: number, stagger: number = MOTION.stagger): number {
  return count > 1 ? Math.min(stagger, MOTION.maxStaggerSpan / (count - 1)) : stagger;
}

export interface MotionMemoryStore {
  has: (id: string) => boolean;
  mark: (id: string) => void;
}

/** Ids of sections that already played their entrance on the current page. */
export const MotionMemoryContext = createContext<MotionMemoryStore | null>(null);

/** True inside a section that already played its entrance: render final states directly. */
export const SettledMotionContext = createContext(false);

export function createMotionMemory(): MotionMemoryStore {
  const seen = new Set<string>();
  return { has: (id) => seen.has(id), mark: (id) => void seen.add(id) };
}

/**
 * True the first time `id` mounts inside the nearest <MotionMemory> (always true without
 * one); false when it re-mounts later, e.g. after a tab switch.
 */
export function useFirstMount(id: string): boolean {
  const memory = useContext(MotionMemoryContext);
  const [first] = useState(() => !memory?.has(id));
  useEffect(() => {
    memory?.mark(id);
  }, [memory, id]);
  return first;
}

/** Whether entrance motion may run here (not reduced motion, not an already-played section). */
export function useEntranceMotion(): boolean {
  const reduced = useReducedMotion();
  const settled = useContext(SettledMotionContext);
  return !reduced && !settled;
}

/** Is any part of the element inside the viewport right now? Hidden elements count as outside. */
export function isInViewport(element: Element): boolean {
  const rect = element.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return false;
  const height = window.innerHeight || document.documentElement.clientHeight;
  const width = window.innerWidth || document.documentElement.clientWidth;
  return rect.bottom > 0 && rect.right > 0 && rect.top < height && rect.left < width;
}
