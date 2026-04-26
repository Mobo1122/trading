"use client";

import type { HealthStatus } from "@/types";

/** Threshold in seconds before an agent is considered stale. */
const AGENT_STALE_THRESHOLD = 600; // 10 minutes
/** Threshold in seconds before an agent is considered inactive. */
const AGENT_INACTIVE_THRESHOLD = 3600; // 1 hour

const AGENT_DISPLAY_NAMES: Record<string, string> = {
  scanner: "Scanner",
  strategist: "Strategist",
  risk_manager: "Risk Manager",
  executor: "Executor",
  regime_detector: "Regime Detector",
  rolling_node: "Rolling",
  approval_gate: "Approval Gate",
};

interface HealthPanelProps {
  health: HealthStatus;
}

/**
 * Mission console: a row of status panels with pulsing dots, then
 * an editorial line stating the system's overall condition, then a
 * vertical agent-activity log. No cards — just typography and rules.
 */
export function HealthPanel({ health }: HealthPanelProps) {
  const connections = [
    { label: "IB Gateway", connected: health.ibConnected, code: "IB" },
    { label: "Database", connected: health.dbConnected, code: "DB" },
    { label: "Redis", connected: health.redisConnected, code: "RD" },
  ];

  const agentEntries = Object.entries(health.agentLastSeen ?? {});
  const allOk =
    health.ibConnected && health.dbConnected && health.redisConnected;
  const verdict = allOk
    ? "all systems are nominal"
    : "one or more subsystems are offline";

  return (
    <div className="rise space-y-12">
      {/* Connection panels */}
      <div className="grid grid-cols-1 md:grid-cols-3 border border-rule">
        {connections.map((c, i) => (
          <ConnectionPanel
            key={c.label}
            label={c.label}
            code={c.code}
            connected={c.connected}
            isLast={i === connections.length - 1}
          />
        ))}
      </div>

      {/* Editorial verdict */}
      <div className="border-t border-rule pt-8 pb-4">
        <div className="eyebrow">Verdict</div>
        <p className="mt-3 font-display text-[44px] sm:text-[56px] leading-[1.05] tracking-tight italic text-foreground">
          The system is {allOk ? "healthy" : "degraded"}
          <span
            className={`mx-3 inline-block h-3 w-3 align-middle ${
              allOk ? "bg-accent pulse" : "bg-negative"
            }`}
            aria-hidden
          />
        </p>
        <p className="mt-2 text-xs text-muted-foreground tracking-wide">
          {verdict}.
        </p>
      </div>

      {/* Pipeline + heartbeat split */}
      <div className="grid grid-cols-1 sm:grid-cols-2 border-y border-rule">
        <SplitPanel
          eyebrow="Pipeline Status"
          value={health.pipelineStatus ?? "unknown"}
          tone={
            health.pipelineStatus === "healthy" ||
            health.pipelineStatus === "running"
              ? "ok"
              : health.pipelineStatus === "idle"
                ? "muted"
                : "warn"
          }
        />
        <SplitPanel
          eyebrow="Last Heartbeat"
          value={relativeTime(health.lastHeartbeat)}
          tone="muted"
          rightAlign
        />
      </div>

      {/* Agent activity log */}
      {agentEntries.length > 0 && (
        <div>
          <div className="flex items-baseline justify-between border-b border-rule pb-3">
            <div className="eyebrow">Agent Activity</div>
            <div className="eyebrow text-rule">Last Seen</div>
          </div>
          <ul>
            {agentEntries.map(([name, lastSeen]) => (
              <li
                key={name}
                className="flex items-center justify-between border-b border-rule py-3 last:border-b-0"
              >
                <span className="flex items-center gap-3">
                  <span
                    className="h-1.5 w-1.5 bg-machine"
                    aria-hidden
                  />
                  <span className="text-[13px] tracking-wide text-foreground">
                    {AGENT_DISPLAY_NAMES[name] ?? name}
                  </span>
                </span>
                <span
                  className={`tnum text-[12px] ${agentStatusColor(lastSeen)}`}
                >
                  {relativeTime(lastSeen)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ConnectionPanel({
  label,
  code,
  connected,
  isLast,
}: {
  label: string;
  code: string;
  connected: boolean;
  isLast: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-between gap-6 px-6 py-7 ${
        isLast ? "" : "md:border-r md:border-rule"
      } border-b border-rule md:border-b-0 last:border-b-0`}
    >
      <div>
        <div className="eyebrow">{code}</div>
        <div className="mt-2 text-[18px] font-medium tracking-tight text-foreground">
          {label}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span
          className={`h-2.5 w-2.5 ${
            connected ? "bg-accent pulse" : "bg-negative"
          }`}
          aria-hidden
        />
        <span
          className={`text-[10px] tracking-[0.18em] uppercase ${
            connected ? "text-accent" : "text-negative"
          }`}
        >
          {connected ? "Online" : "Offline"}
        </span>
      </div>
    </div>
  );
}

function SplitPanel({
  eyebrow,
  value,
  tone,
  rightAlign,
}: {
  eyebrow: string;
  value: string;
  tone: "ok" | "warn" | "muted";
  rightAlign?: boolean;
}) {
  const toneClass =
    tone === "ok"
      ? "text-accent"
      : tone === "warn"
        ? "text-negative"
        : "text-foreground";
  return (
    <div
      className={`px-6 py-6 sm:[&:nth-child(odd)]:border-r sm:border-rule ${
        rightAlign ? "sm:text-right" : ""
      }`}
    >
      <div className="eyebrow">{eyebrow}</div>
      <div className={`mt-2 text-[22px] tnum tracking-tight ${toneClass}`}>
        {value}
      </div>
    </div>
  );
}

function relativeTime(isoString: string | null): string {
  if (!isoString) return "never";
  const diff = (Date.now() - new Date(isoString).getTime()) / 1000;
  if (diff < 0) return "just now";
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function agentStatusColor(isoString: string): string {
  const diffSec = (Date.now() - new Date(isoString).getTime()) / 1000;
  if (diffSec < AGENT_STALE_THRESHOLD) return "text-machine";
  if (diffSec < AGENT_INACTIVE_THRESHOLD) return "text-accent";
  return "text-negative";
}
