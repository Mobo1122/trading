"use client";

import { useCallback, useEffect, useState } from "react";
import { TradeHistory } from "@/components/trades/trade-history";
import { PageHeader, PageMeta } from "@/components/operator/page-header";
import { getTradeHistory } from "@/lib/api";
import type { TradeHistoryItem } from "@/types";

const PAGE_SIZE = 50;

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
      /* non-fatal: keep showing previous data */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTrades(0);
  }, [fetchTrades]);

  return (
    <div className="rise px-8 sm:px-10 py-10 max-w-[1280px]">
      <PageHeader
        number="03"
        section="Ledger"
        title="Trade History"
        lede="Every closed trade with the agent reasoning chain that produced it — the system's complete record of mind."
        meta={<PageMeta label="Total" value={`${total} trades`} />}
      />

      <div className="mt-10">
        {loading && trades.length === 0 ? (
          <div className="border border-rule px-6 py-16 text-center">
            <div className="eyebrow caret">Loading</div>
            <p className="mt-3 text-xs text-muted-foreground">
              fetching trade history
            </p>
          </div>
        ) : (
          <TradeHistory
            trades={trades}
            total={total}
            limit={PAGE_SIZE}
            offset={offset}
            onPageChange={fetchTrades}
          />
        )}
      </div>
    </div>
  );
}
