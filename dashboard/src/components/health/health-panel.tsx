"use client";

import type { HealthStatus } from "@/types";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/** Threshold in seconds before an agent is considered stale. */
const AGENT_STALE_THRESHOLD = 600; // 10 minutes
/** Threshold in seconds before an agent is considered inactive. */
const AGENT_INACTIVE_THRESHOLD = 3600; // 1 hour

/**
 * Render a colored status badge based on boolean connectivity.
 */
function ConnectionBadge({ connected }: { connected: boolean }) {
  return (
    <Badge variant={connected ? "default" : "destructive"}>
      {connected ? "Connected" : "Disconnected"}
    </Badge>
  );
}

/**
 * Compute relative time string from an ISO timestamp.
 */
function relativeTime(isoString: string | null): string {
  if (!isoString) return "Never";
  const diff = (Date.now() - new Date(isoString).getTime()) / 1000;
  if (diff < 0) return "Just now";
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

/**
 * Determine agent status color based on last-seen time.
 */
function agentStatusColor(isoString: string): string {
  const diffSec = (Date.now() - new Date(isoString).getTime()) / 1000;
  if (diffSec < AGENT_STALE_THRESHOLD) return "text-green-400";
  if (diffSec < AGENT_INACTIVE_THRESHOLD) return "text-yellow-400";
  return "text-red-400";
}

/** Known agent display names for readability. */
const AGENT_DISPLAY_NAMES: Record<string, string> = {
  scanner: "Scanner",
  strategist: "Strategist",
  risk_manager: "Risk Manager",
  executor: "Executor",
  regime_detector: "Regime Detector",
};

interface HealthPanelProps {
  health: HealthStatus;
}

/**
 * Health panel showing connection status cards, pipeline status,
 * last heartbeat, and per-agent last-seen activity.
 *
 * Displays colored badges for IB, DB, and Redis connectivity.
 * Agent activity section shows when each pipeline agent last ran,
 * with color-coded freshness warnings.
 */
export function HealthPanel({ health }: HealthPanelProps) {
  const connections = [
    { label: "IB Gateway", connected: health.ibConnected },
    { label: "Database", connected: health.dbConnected },
    { label: "Redis", connected: health.redisConnected },
  ];

  const agentEntries = Object.entries(health.agentLastSeen ?? {});

  return (
    <div className="space-y-6">
      {/* Connection Status */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {connections.map((conn) => (
          <Card key={conn.label} size="sm">
            <CardHeader>
              <CardTitle>{conn.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <ConnectionBadge connected={conn.connected} />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Pipeline & Heartbeat */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Card size="sm">
          <CardHeader>
            <CardTitle>Pipeline Status</CardTitle>
          </CardHeader>
          <CardContent>
            <Badge
              variant={
                health.pipelineStatus === "idle"
                  ? "secondary"
                  : health.pipelineStatus === "running"
                    ? "default"
                    : "destructive"
              }
            >
              {health.pipelineStatus}
            </Badge>
          </CardContent>
        </Card>

        <Card size="sm">
          <CardHeader>
            <CardTitle>Last Heartbeat</CardTitle>
          </CardHeader>
          <CardContent>
            <span className="text-sm text-muted-foreground">
              {relativeTime(health.lastHeartbeat)}
            </span>
          </CardContent>
        </Card>
      </div>

      {/* Agent Activity */}
      {agentEntries.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Agent Activity</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {agentEntries.map(([name, lastSeen]) => (
                <div
                  key={name}
                  className="flex items-center justify-between rounded-md border px-3 py-2"
                >
                  <span className="text-sm font-medium">
                    {AGENT_DISPLAY_NAMES[name] ?? name}
                  </span>
                  <span
                    className={`text-xs font-mono ${agentStatusColor(lastSeen)}`}
                  >
                    {relativeTime(lastSeen)}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
