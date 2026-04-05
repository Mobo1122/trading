"use client";

import { useState } from "react";
import { ScenarioForm } from "@/components/scenarios/scenario-form";
import { ScenarioResults } from "@/components/scenarios/scenario-results";
import { runScenario } from "@/lib/api";
import type { ScenarioResponse } from "@/types";

/**
 * Scenario Analysis page.
 *
 * Allows the user to specify what-if parameters (underlying price
 * change, IV change, days forward) and see the projected impact
 * on their portfolio using Black-Scholes re-pricing.
 *
 * Calls POST /api/scenarios on the backend which runs the scenario
 * engine against current positions.
 */
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
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Scenario Analysis
        </h1>
        <p className="text-sm text-muted-foreground">
          What-if analysis: see how your portfolio responds to market changes
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[400px_1fr]">
        <div>
          <ScenarioForm onSubmit={handleSubmit} loading={loading} />
        </div>

        <div>
          {error && (
            <p className="text-sm text-red-500 mb-4">{error}</p>
          )}

          {result ? (
            <ScenarioResults result={result} />
          ) : (
            <div className="flex items-center justify-center h-64 text-muted-foreground">
              <p>
                Configure scenario parameters and click &quot;Run
                Scenario&quot; to analyze your portfolio.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
