"use client";

import { useEffect, useState } from "react";
import { PortfolioSummary } from "@/components/positions/portfolio-summary";
import { PositionsTable } from "@/components/positions/positions-table";
import { usePositionsStore } from "@/stores/positions-store";
import { getPositions, getPortfolio } from "@/lib/api";

export default function PositionsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const [positions, portfolio] = await Promise.all([
          getPositions(),
          getPortfolio(),
        ]);
        if (cancelled) return;
        const store = usePositionsStore.getState();
        store.setPositions(positions ?? []);
        if (portfolio) store.setPortfolioSummary(portfolio);
        setLoading(false);
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : "Failed to load positions"
        );
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

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
