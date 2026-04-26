"use client";

import { useEffect, useState } from "react";
import { PortfolioSummary } from "@/components/positions/portfolio-summary";
import { PositionsTable } from "@/components/positions/positions-table";
import { PageHeader, PageMeta } from "@/components/operator/page-header";
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

  return (
    <div className="rise px-8 sm:px-10 py-10 max-w-[1280px]">
      <PageHeader
        number="01"
        section="Operating Book"
        title="Open Positions"
        lede="A current accounting of every contract the system holds, marked to market in real time."
        meta={<PageMeta label="Updated" value="live · websocket" />}
      />

      <div className="mt-10 space-y-10">
        <PortfolioSummary />

        {loading ? (
          <div className="border border-rule px-6 py-16 text-center">
            <div className="eyebrow caret">Loading</div>
            <p className="mt-3 text-xs text-muted-foreground">
              fetching positions from the server
            </p>
          </div>
        ) : error ? (
          <div className="border border-negative/40 px-6 py-12 text-center">
            <div className="eyebrow text-negative">Error</div>
            <p className="mt-3 text-xs text-negative">{error}</p>
          </div>
        ) : (
          <PositionsTable />
        )}
      </div>
    </div>
  );
}
