import { Children, useContext, useState, type ReactNode } from "react";
import { motion, useReducedMotion, type Variants } from "motion/react";

import {
  createMotionMemory,
  EASE_OUT,
  MOTION,
  MotionMemoryContext,
  SettledMotionContext,
  staggerStep,
  useEntranceMotion,
  useFirstMount,
} from "@/lib/motion";

const containerVariants: Variants = {
  hidden: {},
  show: (stagger: number) => ({ transition: { staggerChildren: stagger } }),
};

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: MOTION.duration, ease: EASE_OUT } },
};

const itemVariantsReduced: Variants = {
  hidden: { opacity: 1, y: 0 },
  show: { opacity: 1, y: 0 },
};

/**
 * Memory for <AnimateOnce>, so a section that re-mounts while the page stays open (Radix
 * unmounts inactive tab panels) doesn't replay its entrance. `AppShell` provides one per
 * route path: changing `scope` forgets everything, so the next page animates again.
 */
export function MotionMemory({ scope, children }: { scope?: string; children: ReactNode }) {
  const [state, setState] = useState(() => ({ scope, store: createMotionMemory() }));
  if (state.scope !== scope) setState({ scope, store: createMotionMemory() });
  return <MotionMemoryContext.Provider value={state.store}>{children}</MotionMemoryContext.Provider>;
}

/**
 * Children play their entrance the first time `id` mounts inside <MotionMemory>; when it
 * re-mounts (e.g. switching back to a tab) every Stagger, Reveal, CountUp, AiScoreRing and
 * chart inside renders settled.
 */
export function AnimateOnce({ id, children }: { id: string; children: ReactNode }) {
  const first = useFirstMount(id);
  const parentSettled = useContext(SettledMotionContext);
  return <SettledMotionContext.Provider value={parentSettled || !first}>{children}</SettledMotionContext.Provider>;
}

export interface StaggerProps {
  children: ReactNode;
  className?: string;
  /** Seconds between children (default 0.03); compressed so the last child starts by 0.15 s. */
  stagger?: number;
}

/** Container that fades/slides its <StaggerItem> children in one after another on mount. */
export function Stagger({ children, className, stagger = MOTION.stagger }: StaggerProps) {
  const entrance = useEntranceMotion();
  const step = staggerStep(Children.count(children), stagger);
  return (
    <motion.div
      className={className}
      variants={containerVariants}
      custom={step}
      initial={entrance ? "hidden" : false}
      animate="show"
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, className }: { children: ReactNode; className?: string }) {
  const reduced = useReducedMotion();
  return (
    <motion.div className={className} variants={reduced ? itemVariantsReduced : itemVariants}>
      {children}
    </motion.div>
  );
}

/** Single fade/slide-in on mount. */
export function Reveal({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const entrance = useEntranceMotion();
  return (
    <motion.div
      className={className}
      initial={entrance ? { opacity: 0, y: 8 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: MOTION.duration, ease: EASE_OUT, delay }}
    >
      {children}
    </motion.div>
  );
}
