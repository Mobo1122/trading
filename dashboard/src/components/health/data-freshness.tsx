"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

/** Threshold in seconds for stale data warning. */
const STALE_THRESHOLD = 30;
/** Threshold in seconds for dead data (no updates). */
const DEAD_THRESHOLD = 120;

/**
 * Determine freshness status for a data stream based on staleness.
 */
function freshnessStatus(
  seconds: number,
): { label: string; variant: "default" | "secondary" | "destructive" } {
  if (seconds < 0) {
    return { label: "Unknown", variant: "secondary" };
  }
  if (seconds < STALE_THRESHOLD) {
    return { label: "Fresh", variant: "default" };
  }
  if (seconds < DEAD_THRESHOLD) {
    return { label: "Stale", variant: "secondary" };
  }
  return { label: "Dead", variant: "destructive" };
}

interface DataFreshnessProps {
  /** Mapping of symbol to staleness in seconds. */
  freshness: Record<string, number>;
}

/**
 * Data freshness table showing per-symbol staleness status.
 *
 * Each row displays a symbol, time since last update, and a
 * status badge (Fresh, Stale, Dead). Stale and dead streams
 * are visually highlighted with warning colors.
 */
export function DataFreshness({ freshness }: DataFreshnessProps) {
  const entries = Object.entries(freshness).sort(([a], [b]) =>
    a.localeCompare(b),
  );

  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No active data streams.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Symbol</TableHead>
          <TableHead>Last Update</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map(([symbol, seconds]) => {
          const status = freshnessStatus(seconds);
          const isWarning = status.label !== "Fresh";

          return (
            <TableRow
              key={symbol}
              className={isWarning ? "bg-yellow-950/20" : ""}
            >
              <TableCell className="font-mono font-medium">
                {symbol}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {seconds < 0 ? "N/A" : `${seconds.toFixed(1)}s ago`}
              </TableCell>
              <TableCell>
                <Badge variant={status.variant}>{status.label}</Badge>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
