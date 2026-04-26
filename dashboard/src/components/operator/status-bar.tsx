"use client";

import { useEffect, useState } from "react";

import { getHealth, getMode } from "@/lib/api";
import { useHealthStore } from "@/stores/health-store";

/**
 * Cockpit-style status bar fixed at the top of the screen.
 *
 * Shows: brand mark, trading mode (red in LIVE), live UTC clock, IB
 * connection pulse, and a blinking ready cursor. Polls the health and
 * mode endpoints so the bar stays accurate across all pages.
 */
export function StatusBar() {
  const ibConnected = useHealthStore((s) => s.health?.ibConnected ?? false);
  const setHealth = useHealthStore((s) => s.setHealth);
  const [mode, setMode] = useState<"paper" | "live" | "unknown">("unknown");
  const [now, setNow] = useState<string>("--:--:--");

  useEffect(() => {
    setNow(formatNow());
    const id = setInterval(() => setNow(formatNow()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await getHealth();
        if (!cancelled) setHealth(data);
      } catch {
        /* non-fatal */
      }
    }
    poll();
    const id = setInterval(poll, 15_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [setHealth]);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await getMode();
        if (!cancelled) setMode(data.runtimeMode);
      } catch {
        /* non-fatal */
      }
    }
    poll();
    const id = setInterval(poll, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const isLive = mode === "live";

  return (
    <header
      className={`sticky top-0 z-30 grid h-9 grid-cols-[1fr_auto_1fr] items-center border-b px-4 backdrop-blur-md ${
        isLive
          ? "bg-negative/15 border-negative/60"
          : "bg-black/85 border-rule"
      }`}
    >
      {/* left: brand + mode */}
      <div className="flex items-center gap-3 text-[11px] tracking-[0.18em] uppercase">
        <span className="font-display text-[15px] not-italic tracking-normal text-foreground">
          Operator
        </span>
        <span className="text-rule">/</span>
        <span
          className={
            isLive
              ? "text-negative font-medium"
              : "text-muted-foreground"
          }
        >
          {isLive ? "Live Mode" : mode === "paper" ? "Paper Mode" : "Loading"}
        </span>
        {isLive && (
          <span
            className="inline-block h-1.5 w-1.5 bg-negative pulse"
            aria-hidden
          />
        )}
      </div>

      {/* center: live UTC clock */}
      <div className="flex items-center gap-2 text-[11px] tabular-nums tracking-[0.14em] text-foreground">
        <span className="text-muted-foreground">UTC</span>
        <span className="tnum">{now}</span>
      </div>

      {/* right: connection status + cursor */}
      <div className="flex items-center justify-end gap-3 text-[11px] tracking-[0.18em] uppercase">
        <span className="flex items-center gap-2 text-muted-foreground">
          <span
            className={`inline-block h-1.5 w-1.5 ${
              ibConnected ? "bg-accent pulse" : "bg-negative"
            }`}
            aria-hidden
          />
          {ibConnected ? "IB Online" : "IB Offline"}
        </span>
        <span className="text-rule">/</span>
        <span
          className={`caret ${isLive ? "text-negative" : "text-accent"}`}
        >
          {isLive ? "Armed" : "Ready"}
        </span>
      </div>
    </header>
  );
}

function formatNow(): string {
  const d = new Date();
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  const ss = String(d.getUTCSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}
