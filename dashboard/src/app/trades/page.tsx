"use client";

import { useCallback, useEffect, useState } from "react";
import { TradeHistory } from "@/components/trades/trade-history";
import { getTradeHistory } from "@/lib/api";
import type { TradeHistoryItem } from "@/types";

const PAGE_SIZE = 50;

/**
 * Trade History page.
 *
 * Fetches paginated trade history from the backend on mount and when
 * the user navigates between pages. Each trade includes its full agent
 * reasoning chain (scanner -> strategist -> risk_manager -> executor).
 */
export default function TradesPage() {
  const [trades, setTrades] = useState<TradeHistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);

  const fetchTrades = useCallback(async (newOffset: number) => {
    setLoading(true);
    try {
      const result = await getTradeHistory(PAGE_SIZE, newOffset);
      setTrades(result.trades);
      setTotal(result.total);
      setOffset(newOffset);
    } catch {
      // Non-fatal: keep showing previous data
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTrades(0);
  }, [fetchTrades]);

  const handlePageChange = useCallback(
    (newOffset: number) => {
      fetchTrades(newOffset);
    },
    [fetchTrades]
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Trade History
        </h1>
        <p className="text-sm text-muted-foreground">
          Completed trades with agent reasoning chains
        </p>
      </div>

      {loading && trades.length === 0 ? (
        <p className="text-sm text-muted-foreground">Loading trades...</p>
      ) : (
        <TradeHistory
          trades={trades}
          total={total}
          limit={PAGE_SIZE}
          offset={offset}
          onPageChange={handlePageChange}
        />
      )}
    </div>
  );
}
