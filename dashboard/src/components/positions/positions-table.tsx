"use client";

import { useState, useMemo } from "react";
import { usePositionsStore } from "@/stores/positions-store";
import type { Position } from "@/types";

type SortField = keyof Position;
type SortDirection = "asc" | "desc";

/**
 * Brutalist positions table — no chrome, just hairline rules between
 * rows. Tabular numerals throughout, sticky header, sortable columns
 * indicated by an arrow glyph in the amber accent color.
 */
export function PositionsTable() {
  const positionsMap = usePositionsStore((s) => s.positions);
  const positions = Object.values(positionsMap);
  const [sortField, setSortField] = useState<SortField>("symbol");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDirection("asc");
    }
  };

  const sorted = useMemo(() => {
    return [...positions].sort((a, b) => {
      const aVal = a[sortField];
      const bVal = b[sortField];
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

  if (positions.length === 0) {
    return (
      <div className="border border-rule px-6 py-16 text-center">
        <div className="eyebrow">No Open Positions</div>
        <p className="mt-3 text-xs text-muted-foreground">
          The system is observing the market. Trades will appear here when the
          agents act.
        </p>
      </div>
    );
  }

  const headers: { key: SortField; label: string; align?: "right" }[] = [
    { key: "symbol", label: "Symbol" },
    { key: "secType", label: "Type" },
    { key: "quantity", label: "Qty", align: "right" },
    { key: "avgCost", label: "Avg Cost", align: "right" },
    { key: "currentPrice", label: "Last", align: "right" },
    { key: "marketValue", label: "Market Value", align: "right" },
    { key: "unrealizedPnl", label: "P&L $", align: "right" },
    { key: "unrealizedPnlPct", label: "P&L %", align: "right" },
  ];

  return (
    <div className="border border-rule">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-rule bg-muted/40">
            {headers.map((h) => {
              const active = sortField === h.key;
              const indicator = active
                ? sortDirection === "asc"
                  ? "\u25B2"
                  : "\u25BC"
                : "";
              return (
                <th
                  key={h.key}
                  className={`px-4 py-3 ${
                    h.align === "right" ? "text-right" : "text-left"
                  } eyebrow cursor-pointer select-none transition-colors hover:text-foreground ${
                    active ? "text-accent" : ""
                  }`}
                  onClick={() => handleSort(h.key)}
                >
                  <span className="inline-flex items-center gap-1.5">
                    {h.label}
                    {indicator && (
                      <span className="text-[8px] text-accent">
                        {indicator}
                      </span>
                    )}
                  </span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((pos) => {
            const negative = (pos.unrealizedPnl ?? 0) < 0;
            const positive = (pos.unrealizedPnl ?? 0) > 0;
            return (
              <tr
                key={pos.symbol}
                className="border-b border-rule last:border-b-0 transition-colors hover:bg-muted/30"
              >
                <td className="px-4 py-3.5 font-medium text-foreground">
                  {pos.symbol}
                </td>
                <td className="px-4 py-3.5">
                  <span className="inline-flex items-center border border-rule px-2 py-0.5 text-[10px] tracking-[0.14em] uppercase text-muted-foreground">
                    {pos.secType}
                  </span>
                </td>
                <td className="px-4 py-3.5 text-right tnum">{pos.quantity}</td>
                <td className="px-4 py-3.5 text-right tnum text-muted-foreground">
                  {formatUSD(pos.avgCost)}
                </td>
                <td className="px-4 py-3.5 text-right tnum">
                  {formatUSD(pos.currentPrice)}
                </td>
                <td className="px-4 py-3.5 text-right tnum">
                  {formatUSD(pos.marketValue)}
                </td>
                <td
                  className={`px-4 py-3.5 text-right tnum ${
                    negative
                      ? "text-negative"
                      : positive
                        ? "text-accent"
                        : "text-muted-foreground"
                  }`}
                >
                  {formatSignedUSD(pos.unrealizedPnl)}
                </td>
                <td
                  className={`px-4 py-3.5 text-right tnum ${
                    negative
                      ? "text-negative"
                      : positive
                        ? "text-accent"
                        : "text-muted-foreground"
                  }`}
                >
                  {formatPct(pos.unrealizedPnlPct)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function formatUSD(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(v);
}

function formatSignedUSD(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  const abs = Math.abs(v);
  const f = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(abs);
  if (v < 0) return `\u2212${f}`;
  if (v > 0) return `+${f}`;
  return f;
}

function formatPct(v: number | null | undefined): string {
  if (v == null) return "\u2014";
  const sign = v > 0 ? "+" : v < 0 ? "\u2212" : "";
  return `${sign}${Math.abs(v).toFixed(2)}%`;
}
