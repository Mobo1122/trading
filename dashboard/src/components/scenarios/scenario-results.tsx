"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ScenarioResponse, ScenarioPositionResult } from "@/types";

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
 * Format a percentage with sign.
 */
function formatPct(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

/**
 * Return a Tailwind text color class based on sign of value.
 */
function pnlColor(value: number): string {
  if (value > 0) return "text-accent";
  if (value < 0) return "text-negative";
  return "text-muted-foreground";
}

interface ScenarioResultsProps {
  result: ScenarioResponse;
}

/**
 * Scenario analysis results display.
 *
 * Shows four summary cards (Current Value, Scenario Value, P&L, P&L %)
 * followed by a per-position breakdown table showing each position's
 * contribution to the scenario P&L.
 */
export function ScenarioResults({ result }: ScenarioResultsProps) {
  const activePositions = result.perPosition.filter(
    (p: ScenarioPositionResult) => p.status !== "skipped"
  );
  const skippedPositions = result.perPosition.filter(
    (p: ScenarioPositionResult) => p.status === "skipped"
  );

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">
              Current Value
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">
              {formatUSD(result.currentValue)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">
              Scenario Value
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">
              {formatUSD(result.scenarioValue)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">
              P&L Change
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className={`text-2xl font-bold ${pnlColor(result.pnl)}`}>
              {formatUSD(result.pnl)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">
              P&L Change %
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p
              className={`text-2xl font-bold ${pnlColor(result.pnlPercent)}`}
            >
              {formatPct(result.pnlPercent)}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Per-position breakdown table */}
      {activePositions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">
              Per-Position Breakdown
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead className="text-right">Strike</TableHead>
                  <TableHead className="text-right">DTE</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Current</TableHead>
                  <TableHead className="text-right">Scenario</TableHead>
                  <TableHead className="text-right">P&L</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activePositions.map(
                  (pos: ScenarioPositionResult, idx: number) => {
                    const positionPnl = pos.pnl ?? 0;
                    return (
                      <TableRow key={`${pos.symbol ?? ""}-${idx}`}>
                        <TableCell className="font-medium">
                          {pos.symbol ?? ""}
                        </TableCell>
                        <TableCell>{pos.right ?? ""}</TableCell>
                        <TableCell className="text-right">
                          {(pos.strike ?? 0).toFixed(0)}
                        </TableCell>
                        <TableCell className="text-right">
                          {pos.dte ?? 0}
                        </TableCell>
                        <TableCell className="text-right">
                          {pos.quantity ?? 0}
                        </TableCell>
                        <TableCell className="text-right">
                          {formatUSD(pos.currentValue ?? 0)}
                        </TableCell>
                        <TableCell className="text-right">
                          {formatUSD(pos.scenarioValue ?? 0)}
                        </TableCell>
                        <TableCell
                          className={`text-right ${pnlColor(positionPnl)}`}
                        >
                          {formatUSD(positionPnl)}
                        </TableCell>
                      </TableRow>
                    );
                  }
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Skipped positions notice */}
      {skippedPositions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm text-muted-foreground">
              Skipped Positions ({skippedPositions.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1 text-sm text-muted-foreground">
              {skippedPositions.map(
                (pos: ScenarioPositionResult, idx: number) => (
                  <li key={`skipped-${idx}`}>
                    {pos.symbol ?? "Unknown"} &mdash;{" "}
                    {pos.reason ?? "Could not resolve contract details"}
                  </li>
                )
              )}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
