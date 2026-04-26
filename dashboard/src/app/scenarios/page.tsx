"use client";

import { useState } from "react";
import { ScenarioForm } from "@/components/scenarios/scenario-form";
import { ScenarioResults } from "@/components/scenarios/scenario-results";
import { PageHeader, PageMeta } from "@/components/operator/page-header";
import { runScenario } from "@/lib/api";
import type { ScenarioResponse } from "@/types";

export default function ScenariosPage() {
  const [result, setResult] = useState<ScenarioResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(params: {
    underlyingChangePct: number;
    ivChangePct: number;
    daysForward: number;
  }) {
    setLoading(true);
    setError(null);
    try {
      const response = await runScenario({
        underlyingChangePct: params.underlyingChangePct,
        ivChangePct: params.ivChangePct,
        daysForward: params.daysForward,
        riskFreeRate: 0.05,
      });
      setResult(response);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to run scenario analysis"
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rise px-8 sm:px-10 py-10 max-w-[1280px]">
      <PageHeader
        number="06"
        section="What-If"
        title="Scenarios"
        lede="Project the book against shocks — move the underlying, move volatility, advance the clock — and watch the marks adjust."
        meta={<PageMeta label="Engine" value="black-scholes" />}
      />

      <div className="mt-10 grid gap-8 lg:grid-cols-[380px_1fr]">
        <div>
          <ScenarioForm onSubmit={handleSubmit} loading={loading} />
        </div>

        <div>
          {error && (
            <div className="mb-4 border border-negative/40 bg-negative/5 px-5 py-4">
              <div className="eyebrow text-negative">Error</div>
              <p className="mt-2 text-xs text-negative">{error}</p>
            </div>
          )}

          {result ? (
            <ScenarioResults result={result} />
          ) : (
            <div className="border border-rule px-6 py-16 text-center">
              <div className="eyebrow">Awaiting Input</div>
              <p className="mt-3 max-w-md mx-auto font-display italic text-[15px] leading-snug text-muted-foreground">
                Configure scenario parameters at left and run to project the
                portfolio&apos;s response.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
