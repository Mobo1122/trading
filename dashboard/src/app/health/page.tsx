"use client";

import { useEffect, useState, useCallback } from "react";

import type { HealthStatus } from "@/types";
import { getHealth } from "@/lib/api";
import { useHealthStore } from "@/stores/health-store";
import { HealthPanel } from "@/components/health/health-panel";
import { DataFreshness } from "@/components/health/data-freshness";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/** Polling interval for health status in milliseconds. */
const POLL_INTERVAL_MS = 10_000;

/**
 * Health monitoring page.
 *
 * Fetches initial health status from the REST API, then polls
 * every 10 seconds for updates. Also subscribes to the health
 * store for real-time WebSocket updates (whichever arrives first
 * wins). Renders HealthPanel for connection badges and agent
 * activity, and DataFreshness for per-symbol staleness.
 */
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
        err instanceof Error ? err.message : "Failed to fetch health",
      );
    }
  }, [setStoreHealth]);

  // Initial fetch + polling
  useEffect(() => {
    fetchHealth();
    const timer = setInterval(fetchHealth, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchHealth]);

  // Merge WebSocket updates from the store
  const current = storeHealth ?? health;

  if (error && !current) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold tracking-tight">System Health</h1>
        <Card>
          <CardContent className="py-8">
            <p className="text-center text-sm text-destructive">{error}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!current) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold tracking-tight">System Health</h1>
        <Card>
          <CardContent className="py-8">
            <p className="text-center text-sm text-muted-foreground">
              Loading health status...
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">System Health</h1>
        {error && (
          <span className="text-xs text-yellow-400">
            Last poll failed -- showing cached data
          </span>
        )}
      </div>

      <HealthPanel health={current} />

      <Card>
        <CardHeader>
          <CardTitle>Data Stream Freshness</CardTitle>
        </CardHeader>
        <CardContent>
          <DataFreshness freshness={current.dataFreshness ?? {}} />
        </CardContent>
      </Card>
    </div>
  );
}
