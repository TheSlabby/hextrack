import { BrainCircuit, CircleHelp } from "lucide-react";

import { useHealth } from "@/api/queries";
import { AiScoreExplainer } from "@/components/ai/AiScoreExplainer";
import { GlowCard } from "@/components/common/GlowCard";
import { SectionHeader } from "@/components/common/SectionHeader";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import { AI_SCORE_SUMMARY, GRADES, type GradeInfo } from "@/lib/score";

interface Band {
  grade: GradeInfo;
  from: number;
  to: number;
}

/** Grades from D up to S with their 0-100 ranges. */
const BANDS: readonly Band[] = [...GRADES].reverse().map((grade, index, ascending) => {
  const next = ascending[index + 1];
  return { grade, from: grade.min, to: next ? next.min - 1 : 100 };
});

function GradeScale() {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-2 gap-0.5 overflow-hidden rounded-full" aria-hidden="true">
        {BANDS.map((band) => (
          <span
            key={band.grade.grade}
            className="h-full first:rounded-l-full last:rounded-r-full"
            style={{ width: `${band.to - band.from + 1}%`, backgroundColor: band.grade.color, opacity: 0.85 }}
          />
        ))}
      </div>
      <ol className="flex text-center" aria-label="AI Score grades">
        {BANDS.map((band) => (
          <li key={band.grade.grade} className="flex min-w-0 flex-col" style={{ width: `${band.to - band.from + 1}%` }}>
            <span className={cn("font-display text-sm font-bold", band.grade.textClass)}>{band.grade.grade}</span>
            <span className="truncate text-[11px] text-text-muted tabular-nums">
              {band.from}–{band.to}
            </span>
            <span className="sr-only">{band.grade.label}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** One line on the model behind the scores (shares the nav status pill's health query). */
function ModelStatus() {
  const { data } = useHealth();
  if (!data) return <p className="min-h-9 text-xs text-text-muted" aria-hidden="true" />;
  const model = data.model;
  if (!model.loaded) {
    return (
      <div className="flex min-h-9 items-start gap-2 text-xs text-text-secondary">
        <span aria-hidden="true" className="mt-1 size-1.5 shrink-0 rounded-full bg-text-muted" />
        <p>
          No model trained yet. Scores appear after{" "}
          <code className="font-mono whitespace-nowrap text-text">hextrack train --activate</code>.
        </p>
      </div>
    );
  }
  const details = [
    model.n_features ? `Reads ${model.n_features} stats per game` : null,
    "scores every stored ranked game",
  ].filter(Boolean);
  return (
    <div className="flex min-h-9 items-start gap-2 text-xs">
      <span
        aria-hidden="true"
        className="mt-1 size-1.5 shrink-0 rounded-full bg-cyan shadow-[0_0_8px_rgba(10,200,185,0.8)]"
      />
      {/* The version id means nothing to a player: it stays in the title, the date is shown. */}
      <p className="flex min-w-0 flex-col gap-0.5" title={model.version ?? undefined}>
        <span className="truncate font-medium text-text">
          {model.trained_at ? `AI model trained ${formatDate(model.trained_at)}` : "AI model loaded"}
        </span>
        {details.length > 0 ? <span className="truncate text-text-muted">{details.join(" · ")}</span> : null}
      </p>
    </div>
  );
}

/** Home teaser for the AI Score: summary, the grade scale and the full explainer dialog. */
export function AiScoreTeaser({ className }: { className?: string }) {
  return (
    <section aria-labelledby="home-ai-title" className={cn("flex flex-col gap-5", className)}>
      <SectionHeader
        eyebrow="Under the hood"
        icon={BrainCircuit}
        title={<span id="home-ai-title">How the AI Score works</span>}
      />
      <GlowCard glow="cyan" className="relative flex flex-1 flex-col gap-5 overflow-clip p-5 sm:p-6">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -top-24 -right-20 size-64 rounded-full bg-[radial-gradient(closest-side,rgba(10,200,185,0.14),transparent)]"
        />
        <p className="relative text-[15px] leading-relaxed text-text-secondary">{AI_SCORE_SUMMARY}</p>

        <div className="relative">
          <GradeScale />
        </div>

        <div className="relative mt-auto flex flex-col gap-4">
          <ModelStatus />
          <div>
            <AiScoreExplainer
              trigger={
                <Button variant="ai" size="sm">
                  <CircleHelp aria-hidden="true" />
                  How it's calculated
                </Button>
              }
            />
          </div>
        </div>
      </GlowCard>
    </section>
  );
}
