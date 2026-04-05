"use client";

import { useEffect, useState } from "react";
import { PortfolioSummary } from "@/components/positions/portfolio-summary";
import { PositionsTable } from "@/components/positions/positions-table";
import { usePositionsStore } from "@/stores/positions-store";
import { getPositions, getPortfolio } from "@/lib/api";

/**
 * Positions page -- the primary dashboard view.
 *
 * On mount, fetches initial positions and portfolio summary from the
 * REST API and hydrates the Zustand store. Real-time updates arrive
 * via WebSocket through the WsProvider in the root layout.
 */
export default function PositionsPage() {
  const setPositions = usePositionsStore((state) => state.setPositions);
  const setPortfolioSummary = usePositionsStore(
    (state) => state.setPortfolioSummary
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadInitialData() {
      try {
        const [positions, portfolio] = await Promise.all([
          getPositions(),
          getPortfolio(),
        ]);

        if (!cancelled) {
          setPositions(positions);
          setPortfolioSummary(portfolio);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Failed to load positions"
          );
          setLoading(false);
        }
      }
    }

    loadInitialData();

    return () => {
      cancelled = true;
    };
  }, [setPositions, setPortfolioSummary]);

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Positions & P&L</h1>
        <p className="text-muted-foreground">Loading positions...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Positions & P&L</h1>
        <p className="text-red-500">{error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Positions & P&L</h1>
      <PortfolioSummary />
      <PositionsTable />
    </div>
  );
}
