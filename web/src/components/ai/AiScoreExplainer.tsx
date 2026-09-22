import { isValidElement, type ReactNode } from "react";
import { BrainCircuit, CircleHelp, Info, Scale, Sparkles, Target } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useHealth, useMeta } from "@/api/queries";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import { AI_AVERAGE_NOTE, AI_SCORE_RESULT_NOTE, AI_SCORE_SUMMARY, GRADES } from "@/lib/score";

import { gradeRange } from "./insights";

export interface AiScoreExplainerProps {
  /**
   * Element that opens the dialog. A single element is used as-is (it must accept a ref and
   * onClick, like <Button>); text is wrapped in a small button. Defaults to "How it works".
   */
  trigger?: ReactNode;
}

/** Dialog that explains the AI Score in plain language: how it is made, the grades, caveats. */
export function AiScoreExplainer({ trigger }: AiScoreExplainerProps) {
  return (
    <Dialog>
      <DialogTrigger asChild>{renderTrigger(trigger)}</DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] gap-0 overflow-y-auto overscroll-contain p-0 scrollbar-thin sm:max-w-2xl">
        <ExplainerBody />
      </DialogContent>
    </Dialog>
  );
}

function renderTrigger(trigger: ReactNode) {
  if (isValidElement(trigger)) return trigger;
  return (
    <Button variant="ghost" size="xs" className="text-text-secondary">
      <CircleHelp className="text-cyan" aria-hidden="true" />
      {trigger ?? "How it works"}
    </Button>
  );
}

interface Step {
  icon: LucideIcon;
  title: string;
  body: string;
}

const STEPS: readonly Step[] = [
  {
    icon: BrainCircuit,
    title: "Learns from ranked games",
    body: "A neural network studies the stat lines of every player in stored ranked games, winners and losers alike, and learns what winning lines look like.",
  },
  {
    icon: Scale,
    title: "Fair across game lengths",
    body: "Stats are normalised per minute and per gold earned, so a 22-minute stomp and a 45-minute slog are judged on the same footing.",
  },
  {
    icon: Target,
    title: "Scores your stat line",
    body: "Your own stats go in, the result does not. Gold, towers and objectives mostly come with winning, though, so the score largely follows it: wins usually score 65+ and losses under 35.",
  },
];

function ExplainerBody() {
  const meta = useMeta();
  const health = useHealth();
  const version = meta.data?.model_version ?? health.data?.model.version ?? null;
  const trainedAt = meta.data?.model_trained_at ?? health.data?.model.trained_at ?? null;
  const features = health.data?.model.n_features ?? null;

  return (
    <>
      <div className="relative overflow-hidden rounded-t-2xl border-b border-border px-6 pt-6 pb-5">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -top-24 left-1/2 h-48 w-[28rem] -translate-x-1/2 rounded-full bg-cyan/10 blur-3xl"
        />
        <DialogHeader className="relative gap-2 text-left">
          <span className="label-caps flex items-center gap-1.5 text-cyan">
            <Sparkles className="size-3.5" aria-hidden="true" />
            AI Score
          </span>
          <DialogTitle className="text-xl sm:text-2xl">How the AI Score works</DialogTitle>
          <DialogDescription className="max-w-prose leading-relaxed">{AI_SCORE_SUMMARY}</DialogDescription>
        </DialogHeader>
      </div>

      <div className="flex flex-col gap-6 px-6 py-5">
        <ol className="grid gap-3 sm:grid-cols-3">
          {STEPS.map((step, i) => (
            <li
              key={step.title}
              className="flex gap-3 rounded-xl border border-border bg-surface-2 p-3.5 sm:flex-col sm:gap-2 sm:p-4"
            >
              <div className="flex shrink-0 items-start gap-2.5 sm:items-center">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-cyan/25 bg-cyan/8 text-cyan">
                  <step.icon className="size-4" aria-hidden="true" />
                </span>
                <span className="hidden font-display text-xs font-semibold tabular-nums text-text-muted sm:inline">
                  0{i + 1}
                </span>
              </div>
              <div className="flex min-w-0 flex-col gap-1 sm:gap-2">
                <p className="text-sm font-semibold text-text">{step.title}</p>
                <p className="text-[13px] leading-relaxed text-text-secondary">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>

        <section aria-labelledby="ai-grades-heading" className="flex flex-col gap-3">
          <h3 id="ai-grades-heading" className="label-caps font-sans">
            Grades
          </h3>
          <GradeScale />
          <table className="w-full text-sm">
            <caption className="sr-only">AI Score grades and their score ranges</caption>
            <thead className="sr-only">
              <tr>
                <th scope="col">Grade</th>
                <th scope="col">Score range</th>
                <th scope="col">Meaning</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {GRADES.map((grade) => {
                const range = gradeRange(grade.grade);
                return (
                  <tr key={grade.grade} className="align-top">
                    <th scope="row" className="w-12 py-2.5 pr-3 text-left">
                      <span
                        className={cn(
                          "inline-flex size-7 items-center justify-center rounded-lg border font-display text-sm font-bold",
                          grade.pillClass,
                        )}
                      >
                        {grade.grade}
                      </span>
                    </th>
                    <td className="w-20 py-2.5 pr-3 pt-3.5 font-medium whitespace-nowrap tabular-nums text-text">
                      {range.lo}–{range.hi}
                    </td>
                    <td className="py-2.5 pt-3">
                      <span className="font-medium text-text">{grade.label}</span>
                      <span className="block text-[13px] leading-relaxed text-text-secondary">{grade.description}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>

        <section aria-labelledby="ai-caveats-heading" className="flex flex-col gap-3">
          <h3 id="ai-caveats-heading" className="label-caps font-sans">
            Keep in mind
          </h3>
          <ul className="flex flex-col gap-2.5 text-[13px] leading-relaxed text-text-secondary">
            <Caveat>
              <strong className="font-medium text-text">No role or champion context yet.</strong> Every stat line is
              judged against all roles, so supports and tanks can score lower for games that were genuinely strong.
            </Caveat>
            <Caveat>
              <strong className="font-medium text-text">Compare games with the same result.</strong>{" "}
              {AI_SCORE_RESULT_NOTE}
            </Caveat>
            <Caveat>
              <strong className="font-medium text-text">Averages aren't graded.</strong> {AI_AVERAGE_NOTE}
            </Caveat>
            <Caveat>
              <strong className="font-medium text-text">Scores compare within one model.</strong> When the model is
              retrained, stored games are re-scored so averages stay comparable.
            </Caveat>
          </ul>
        </section>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-border bg-surface-2/60 px-4 py-3 text-xs text-text-secondary">
          <span className="label-caps">Current model</span>
          {version ? (
            <>
              <code className="rounded-md border border-cyan/25 bg-cyan/8 px-1.5 py-0.5 font-mono text-[11px] text-cyan">
                {version}
              </code>
              {trainedAt ? <span>Trained {formatDate(trainedAt)}</span> : null}
              {features ? <span className="tabular-nums">{features} input stats</span> : null}
            </>
          ) : meta.isPending && health.isPending ? (
            <span className="text-text-muted">Loading…</span>
          ) : (
            <span>No model trained yet, so games are not scored.</span>
          )}
        </div>
      </div>

      <DialogFooter className="border-t border-border px-6 py-4">
        <DialogClose asChild>
          <Button variant="outline">Got it</Button>
        </DialogClose>
      </DialogFooter>
    </>
  );
}

function Caveat({ children }: { children: ReactNode }) {
  return (
    <li className="flex gap-2.5">
      <Info className="mt-0.5 size-4 shrink-0 text-text-muted" aria-hidden="true" />
      <span>{children}</span>
    </li>
  );
}

/** The 0–100 scale split into grade bands, lettered, so colour is never the only signal. */
function GradeScale() {
  const bands = [...GRADES].reverse();
  return (
    <div aria-hidden="true" className="flex flex-col gap-1.5">
      <div className="flex h-7 gap-0.5 overflow-hidden rounded-lg">
        {bands.map((grade) => {
          const range = gradeRange(grade.grade);
          const width = range.hi - range.lo + (range.hi === 100 ? 0 : 1);
          return (
            <div
              key={grade.grade}
              className="flex items-center justify-center font-display text-xs font-bold text-bg"
              style={{ flexGrow: width, flexBasis: 0, backgroundColor: grade.color }}
            >
              {grade.grade}
            </div>
          );
        })}
      </div>
      <div className="relative h-4 text-[11px] tabular-nums text-text-muted">
        {[0, 35, 50, 65, 80, 100].map((tick) => (
          <span
            key={tick}
            className={cn(
              "absolute top-0",
              tick === 0 ? "left-0" : tick === 100 ? "right-0" : "-translate-x-1/2",
            )}
            style={tick === 0 || tick === 100 ? undefined : { left: `${tick}%` }}
          >
            {tick}
          </span>
        ))}
      </div>
    </div>
  );
}
