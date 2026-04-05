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

  const totalMarketValue = summary?.totalMarketValue ?? 0;
  const unrealizedPnl = summary?.totalUnrealizedPnl ?? 0;
  const realizedPnl = summary?.totalRealizedPnl ?? 0;
  const netLiquidation = summary?.netLiquidation ?? 0;

  return (
    <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm text-muted-foreground">
            Total Market Value
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{formatUSD(totalMarketValue)}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm text-muted-foreground">
            Unrealized P&L
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className={`text-2xl font-bold ${pnlColor(unrealizedPnl)}`}>
            {formatUSD(unrealizedPnl)}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm text-muted-foreground">
            Realized P&L
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className={`text-2xl font-bold ${pnlColor(realizedPnl)}`}>
            {formatUSD(realizedPnl)}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm text-muted-foreground">
            Net Liquidation
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{formatUSD(netLiquidation)}</p>
        </CardContent>
      </Card>
    </div>
  );
}
