import { useLayoutEffect, useRef, useState } from "react";
import { animate as animateValue } from "motion/react";

import { EASE_OUT, isInViewport, MOTION, useEntranceMotion } from "@/lib/motion";

export interface CountUpProps {
  value: number;
  /** Formats intermediate and final values (default: rounded integer). */
  format?: (value: number) => string;
  duration?: number;
  /** Set false to always render the final value. */
  animate?: boolean;
  className?: string;
}

const defaultFormat = (value: number) => Math.round(value).toString();

/**
 * A number that counts up from 0 once, on first paint, and only when it is on screen at that
 * moment. Everything else (off screen, reduced motion, an already-played section, later value
 * changes) renders the final value straight away, so no number is ever left showing "0".
 */
export function CountUp({ value, format = defaultFormat, duration = MOTION.countUp, animate = true, className }: CountUpProps) {
  const ref = useRef<HTMLSpanElement>(null);
  /** Mid-animation value, or null to render `value` itself. */
  const [display, setDisplay] = useState<number | null>(null);
  const current = useRef<number | null>(null);
  /** True once the first paint has animated or been skipped: no count-up after that. */
  const settled = useRef(false);
  const entrance = useEntranceMotion();

  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    // `current` is set when StrictMode (or a value change) re-runs this mid-animation: keep going.
    const start = !settled.current && animate && entrance && (current.current !== null || isInViewport(node));
    if (!start) {
      settled.current = true;
      current.current = null;
      setDisplay(null);
      return;
    }
    const from = current.current ?? 0;
    current.current = from;
    setDisplay(from);
    const controls = animateValue(from, value, {
      duration,
      ease: EASE_OUT,
      onUpdate: (latest) => {
        current.current = latest;
        setDisplay(latest);
      },
      onComplete: () => {
        settled.current = true;
        current.current = null;
        setDisplay(null);
      },
    });
    return () => controls.stop();
  }, [value, duration, animate, entrance]);

  // The animated digits are hidden from assistive tech; screen readers get the final value.
  return (
    <span className={className}>
      <span ref={ref} aria-hidden="true">
        {format(display ?? value)}
      </span>
      <span className="sr-only">{format(value)}</span>
    </span>
  );
}
