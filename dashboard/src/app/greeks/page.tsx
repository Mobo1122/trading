"use client";

import { useEffect } from "react";
import { GreeksDisplay } from "@/components/greeks/greeks-display";
import { useGreeksStore } from "@/stores/greeks-store";
import { getGreeks } from "@/lib/api";

/**
 * Portfolio Greeks page.
 *
 * Fetches initial Greeks on mount and polls every 10 seconds as a
 * WebSocket fallback. The WebSocket portfolio_greeks channel provides
 * real-time pushes, but polling ensures data freshness if WS delivery
 * is delayed or missed.
 */
export default function GreeksPage() {
  const setPortfolioGreeks = useGreeksStore((s) => s.setPortfolioGreeks);

  useEffect(() => {
    let mounted = true;

    async function fetchGreeks() {
      try {
        const greeks = await getGreeks();
        if (mounted) {
          setPortfolioGreeks(greeks);
        }
      } catch {
        // Non-fatal: will retry on next poll interval
      }
    }

    // Initial fetch
    fetchGreeks();

    // Poll every 10 seconds as WebSocket fallback
    const interval = setInterval(fetchGreeks, 10_000);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [setPortfolioGreeks]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Portfolio Greeks
        </h1>
        <p className="text-sm text-muted-foreground">
          Real-time aggregated Greeks exposure across all positions
        </p>
      </div>
      <GreeksDisplay />
    </div>
  );
}
