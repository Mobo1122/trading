"use client";

import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ReasoningChain } from "@/components/trades/reasoning-chain";
import type { TradeHistoryItem } from "@/types";

/**
 * Format a currency value for display.
 */
function formatCurrency(value: number | null): string {
  if (value == null) return "--";
  return `$${value.toFixed(2)}`;
}

/**
 * Paginated trade history table with expandable reasoning chains.
 *
 * Each row shows trade details (time, symbol, action, qty, fill price,
 * commission). Clicking "View" expands the row to show the full agent
 * reasoning chain (scanner -> strategist -> risk_manager -> executor).
 *
 * Pagination controls at the bottom show current range and allow
 * navigating between pages.
 */
export function TradeHistory({
  trades,
  total,
  limit,
  offset,
  onPageChange,
}: {
  trades: TradeHistoryItem[];
  total: number;
  limit: number;
  offset: number;
  onPageChange: (offset: number) => void;
}) {
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const start = offset + 1;
  const end = Math.min(offset + trades.length, total);
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <div className="space-y-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>Symbol</TableHead>
            <TableHead>Action</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead className="text-right">Fill Price</TableHead>
            <TableHead className="text-right">Commission</TableHead>
            <TableHead>Reasoning</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={7}
                className="text-center text-muted-foreground py-8"
              >
                No filled trades yet.
              </TableCell>
            </TableRow>
          )}
          {trades.map((trade) => {
            const isExpanded = expandedRow === trade.orderId;
            const actionColor =
              trade.action === "BUY"
                ? "bg-green-500/20 text-green-400 border-green-500/30"
                : "bg-red-500/20 text-red-400 border-red-500/30";

            return (
              <>
                <TableRow key={trade.orderId}>
                  <TableCell
                    title={trade.createdAt}
                    className="text-muted-foreground"
                  >
                    {formatDistanceToNow(new Date(trade.createdAt), {
                      addSuffix: true,
                    })}
                  </TableCell>
                  <TableCell className="font-medium">{trade.symbol}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={actionColor}>
                      {trade.action}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {trade.quantity}
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {formatCurrency(trade.fillPrice)}
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {formatCurrency(trade.commission)}
                  </TableCell>
                  <TableCell>
                    {trade.reasoningChain && trade.reasoningChain.length > 0 ? (
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() =>
                          setExpandedRow(isExpanded ? null : trade.orderId)
                        }
                        aria-expanded={isExpanded}
                      >
                        {isExpanded ? "Hide" : "View"}
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">--</span>
                    )}
                  </TableCell>
                </TableRow>
                {isExpanded && trade.reasoningChain && (
                  <TableRow key={`${trade.orderId}-chain`}>
                    <TableCell colSpan={7} className="bg-muted/30">
                      <ReasoningChain chain={trade.reasoningChain} />
                    </TableCell>
                  </TableRow>
                )}
              </>
            );
          })}
        </TableBody>
      </Table>

      {/* Pagination controls */}
      {total > 0 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">
            Showing {start}-{end} of {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={!hasPrev}
              onClick={() => onPageChange(Math.max(0, offset - limit))}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!hasNext}
              onClick={() => onPageChange(offset + limit)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
