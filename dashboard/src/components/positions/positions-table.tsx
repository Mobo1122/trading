"use client";

import { useState, useMemo } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { usePositionsStore } from "@/stores/positions-store";
import type { Position } from "@/types";

type SortField = keyof Position;
type SortDirection = "asc" | "desc";

/**
 * Format a number as USD currency.
 */
function formatUSD(value: number | null | undefined): string {
  if (value == null) return "--";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/**
 * Format a percentage value with sign.
 */
function formatPct(value: number | null | undefined): string {
  if (value == null) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

/**
 * Return a tailwind text color class based on sign of value.
 */
function pnlColor(value: number | null | undefined): string {
  if (value == null) return "";
  if (value > 0) return "text-green-500";
  if (value < 0) return "text-red-500";
  return "";
}

/**
 * Sortable table of open positions with real-time P&L.
 *
 * Columns: Symbol, Type, Qty, Avg Cost, Current Price,
 * Market Value, P&L ($), P&L (%).
 *
 * Clicking a column header sorts by that field. Clicking again
 * reverses the direction.
 */
export function PositionsTable() {
  const positions = usePositionsStore((state) =>
    Object.values(state.positions)
  );
  const [sortField, setSortField] = useState<SortField>("symbol");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDirection("asc");
    }
  };

  const sorted = useMemo(() => {
    return [...positions].sort((a, b) => {
      const aVal = a[sortField];
      const bVal = b[sortField];

      // Handle nulls
      if (aVal == null && bVal == null) return 0;
      if (aVal == null) return 1;
      if (bVal == null) return -1;

      let cmp = 0;
      if (typeof aVal === "string" && typeof bVal === "string") {
        cmp = aVal.localeCompare(bVal);
      } else {
        cmp = Number(aVal) - Number(bVal);
      }

      return sortDirection === "asc" ? cmp : -cmp;
    });
  }, [positions, sortField, sortDirection]);

  const sortIndicator = (field: SortField) => {
    if (sortField !== field) return "";
    return sortDirection === "asc" ? " \u2191" : " \u2193";
  };

  if (positions.length === 0) {
    return (
      <div className="flex items-center justify-center p-12 text-muted-foreground">
        No open positions
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead
            className="cursor-pointer select-none"
            onClick={() => handleSort("symbol")}
          >
            Symbol{sortIndicator("symbol")}
          </TableHead>
          <TableHead
            className="cursor-pointer select-none"
            onClick={() => handleSort("secType")}
          >
            Type{sortIndicator("secType")}
          </TableHead>
          <TableHead
            className="cursor-pointer select-none text-right"
            onClick={() => handleSort("quantity")}
          >
            Qty{sortIndicator("quantity")}
          </TableHead>
          <TableHead
            className="cursor-pointer select-none text-right"
            onClick={() => handleSort("avgCost")}
          >
            Avg Cost{sortIndicator("avgCost")}
          </TableHead>
          <TableHead
            className="cursor-pointer select-none text-right"
            onClick={() => handleSort("currentPrice")}
          >
            Current Price{sortIndicator("currentPrice")}
          </TableHead>
          <TableHead
            className="cursor-pointer select-none text-right"
            onClick={() => handleSort("marketValue")}
          >
            Market Value{sortIndicator("marketValue")}
          </TableHead>
          <TableHead
            className="cursor-pointer select-none text-right"
            onClick={() => handleSort("unrealizedPnl")}
          >
            P&L ($){sortIndicator("unrealizedPnl")}
          </TableHead>
          <TableHead
            className="cursor-pointer select-none text-right"
            onClick={() => handleSort("unrealizedPnlPct")}
          >
            P&L (%){sortIndicator("unrealizedPnlPct")}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((pos) => (
          <TableRow key={pos.symbol}>
            <TableCell className="font-medium">{pos.symbol}</TableCell>
            <TableCell>
              <Badge variant={pos.secType === "OPT" ? "secondary" : "outline"}>
                {pos.secType}
              </Badge>
            </TableCell>
            <TableCell className="text-right">{pos.quantity}</TableCell>
            <TableCell className="text-right">
              {formatUSD(pos.avgCost)}
            </TableCell>
            <TableCell className="text-right">
              {formatUSD(pos.currentPrice)}
            </TableCell>
            <TableCell className="text-right">
              {formatUSD(pos.marketValue)}
            </TableCell>
            <TableCell
              className={`text-right ${pnlColor(pos.unrealizedPnl)}`}
            >
              {formatUSD(pos.unrealizedPnl)}
            </TableCell>
            <TableCell
              className={`text-right ${pnlColor(pos.unrealizedPnlPct)}`}
            >
              {formatPct(pos.unrealizedPnlPct)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
