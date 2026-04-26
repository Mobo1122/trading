"use client";

import { useEffect, useState } from "react";

import { getHealth } from "@/lib/api";
import { useHealthStore } from "@/stores/health-store";

/**
 * Cockpit-style status bar fixed at the top of the screen.
 *
 * Shows: brand mark, trading mode, live UTC clock, IB connection
 * pulse, and a blinking ready cursor. Everything monospaced and
 * tracked-out — the kind of strip you'd see at the top of a
 * Bloomberg Terminal or a NASA console.
 */
export function StatusBar() {
  const ibConnected = useHealthStore((s) => s.health?.ibConnected ?? false);
  const setHealth = useHealthStore((s) => s.setHealth);
  // Render an empty placeholder during SSR so the server and the first
  // client paint agree. Once mounted we tick once a second.
  const [now, setNow] = useState<string>("--:--:--");

  useEffect(() => {
    setNow(formatNow());
    const id = setInterval(() => setNow(formatNow()), 1000);
    return () => clearInterval(id);
  }, []);

  // Light-weight health poll so the global status bar stays accurate
  // regardless of which page is currently mounted.
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await getHealth();
        if (!cancelled) setHealth(data);
      } catch {
        /* non-fatal — bar stays in last-known state */
      }
    }
    poll();
    const id = setInterval(poll, 15_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [setHealth]);

  return (
    <header className="sticky top-0 z-30 grid h-9 grid-cols-[1fr_auto_1fr] items-center border-b border-rule bg-black/85 px-4 backdrop-blur-md">
      {/* left: brand + mode */}
      <div className="flex items-center gap-3 text-[11px] tracking-[0.18em] uppercase">
        <span className="font-display text-[15px] not-italic tracking-normal text-foreground">
          Operator
        </span>
        <span className="text-rule">/</span>
        <span className="text-muted-foreground">Paper Mode</span>
      </div>

      {/* center: live UTC clock — the heartbeat of the room */}
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
        <span className="text-accent caret">Ready</span>
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
