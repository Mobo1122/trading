"use client";

import { useEffect, useState, useCallback } from "react";

import type { HealthStatus } from "@/types";
import { getHealth } from "@/lib/api";
import { useHealthStore } from "@/stores/health-store";
import { HealthPanel } from "@/components/health/health-panel";
import { DataFreshness } from "@/components/health/data-freshness";
import { PageHeader, PageMeta } from "@/components/operator/page-header";

const POLL_INTERVAL_MS = 10_000;

export default function HealthPage() {
  const storeHealth = useHealthStore((s) => s.health);
  const setStoreHealth = useHealthStore((s) => s.setHealth);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      const data = await getHealth();
      setHealth(data);
      setStoreHealth(data);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to fetch health"
      );
    }
  }, [setStoreHealth]);

  useEffect(() => {
    fetchHealth();
    const timer = setInterval(fetchHealth, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchHealth]);

  const current = storeHealth ?? health;

  return (
    <div className="rise px-8 sm:px-10 py-10 max-w-[1280px]">
      <PageHeader
        number="05"
        section="Mission Console"
        title="System Health"
        lede="The console reports on the wellbeing of every subsystem the operator depends on."
        meta={<PageMeta label="Polling" value="every 10s" />}
      />

      <div className="mt-10">
        {error && !current ? (
          <div className="border border-negative/40 px-6 py-12 text-center">
            <div className="eyebrow text-negative">Console Error</div>
            <p className="mt-3 text-xs text-negative">{error}</p>
          </div>
        ) : !current ? (
          <div className="border border-rule px-6 py-16 text-center">
            <div className="eyebrow caret">Probing</div>
            <p className="mt-3 text-xs text-muted-foreground">
              awaiting first health report
            </p>
          </div>
        ) : (
          <div className="space-y-12">
            <HealthPanel health={current} />

            <div>
              <div className="border-b border-rule pb-3">
                <div className="eyebrow">Data Stream Freshness</div>
              </div>
              <div className="mt-4">
                <DataFreshness freshness={current.dataFreshness ?? {}} />
              </div>
            </div>

            {error && (
              <p className="border-t border-rule pt-4 text-[10px] tracking-[0.18em] uppercase text-accent">
                last poll failed — showing cached data
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
