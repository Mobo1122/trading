"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { usePositionsStore } from "@/stores/positions-store";

/**
 * Format a number as USD currency.
 */
function formatUSD(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/**
 * Return a tailwind text color class based on sign of value.
 * Positive = green, negative = red, zero = default.
 */
function pnlColor(value: number): string {
  if (value > 0) return "text-green-500";
  if (value < 0) return "text-red-500";
  return "text-muted-foreground";
}

/**
 * Portfolio-level P&L summary displayed as 4 metric cards.
 *
 * Shows Total Market Value, Unrealized P&L, Realized P&L,
 * and Net Liquidation. Reads from the positions Zustand store
 * and updates in real-time as WebSocket data arrives.
 */
export function PortfolioSummary() {
  const summary = usePositionsStore((state) => state.portfolioSummary);

  if (!summary) {
    return (
      <p className="text-muted-foreground">No portfolio data available.</p>
    );
  }

  const metrics = [
    { label: "Total Market Value", value: summary.totalMarketValue, color: false },
    { label: "Unrealized P&L", value: summary.totalUnrealizedPnl, color: true },
    { label: "Realized P&L", value: summary.totalRealizedPnl, color: true },
    { label: "Net Liquidation", value: summary.netLiquidation, color: false },
  ];

  return (
    <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
      {metrics.map((m) => (
        <Card key={m.label}>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">
              {m.label}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className={`text-2xl font-bold ${m.color ? pnlColor(m.value) : ""}`}>
              {formatUSD(m.value)}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
