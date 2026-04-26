"use client";

import { Badge } from "@/components/ui/badge";
import type { ReasoningStep } from "@/types";

/**
 * Color mapping for pipeline agent badges.
 *
 * Each agent in the pipeline gets a distinct color for visual
 * identification in the reasoning chain timeline.
 */
/* All agents share the cyan "machine" signal — they're all the same
 * autonomous system speaking. Differentiation by agent name is enough;
 * adding 5 hue variations would dilute the palette. */
const AGENT_COLORS: Record<string, string> = {
  scanner: "bg-machine/15 text-machine border-machine/30",
  strategist: "bg-machine/15 text-machine border-machine/30",
  risk_manager: "bg-machine/15 text-machine border-machine/30",
  executor: "bg-machine/15 text-machine border-machine/30",
  regime_detector: "bg-machine/15 text-machine border-machine/30",
};

/**
 * Format agent name for display (replace underscores with spaces, title case).
 */
function formatAgentName(name: string): string {
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/**
 * Agent reasoning chain display showing each pipeline stage.
 *
 * Renders a vertical timeline with color-coded agent badges, reasoning
 * text, output summary, and duration for each pipeline stage that
 * contributed to the trade decision.
 */
export function ReasoningChain({ chain }: { chain: ReasoningStep[] }) {
  if (!chain || chain.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-2">
        No reasoning chain available for this trade.
      </p>
    );
  }

  return (
    <div className="space-y-3 py-2">
      {chain.map((step, index) => {
        const colors = AGENT_COLORS[step.agent] ?? "bg-muted text-foreground";

        return (
          <div key={index} className="flex gap-3 items-start">
            {/* Timeline connector */}
            <div className="flex flex-col items-center pt-1">
              <div className="h-2 w-2 rounded-full bg-muted-foreground" />
              {index < chain.length - 1 && (
                <div className="w-px h-full min-h-[2rem] bg-border" />
              )}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2 mb-1">
                <Badge variant="outline" className={colors}>
                  {formatAgentName(step.agent)}
                </Badge>
                {step.durationMs != null && (
                  <span className="text-xs text-muted-foreground font-mono shrink-0">
                    {step.durationMs}ms
                  </span>
                )}
              </div>

              {step.reasoning && (
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {step.reasoning}
                </p>
              )}

              {step.outputSummary && (
                <p className="text-xs text-muted-foreground/70 mt-1">
                  {step.outputSummary}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
