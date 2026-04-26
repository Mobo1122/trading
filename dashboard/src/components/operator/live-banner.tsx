"use client";

import { useEffect, useState } from "react";

import { getMode } from "@/lib/api";

/**
 * Persistent warning banner shown across every page when the system is
 * in live mode. The banner is intentionally loud — magenta text on a
 * tinted strip — to make it impossible for the operator to forget
 * which mode they're in while skimming a page.
 */
export function LiveBanner() {
  const [isLive, setIsLive] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await getMode();
        if (!cancelled) setIsLive(data.runtimeMode === "live");
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

  if (!isLive) return null;

  return (
    <div className="border-b border-negative/60 bg-negative/15 px-6 py-2.5">
      <div className="flex items-center gap-3 text-[11px] tracking-[0.16em] uppercase">
        <span
          className="inline-block h-1.5 w-1.5 bg-negative pulse"
          aria-hidden
        />
        <span className="text-negative font-medium">Live Mode Active</span>
        <span className="text-rule">·</span>
        <span className="text-muted-foreground">
          Real orders are flowing to your IBKR account. Switch back to paper
          via the{" "}
          <a
            href="/mode"
            className="text-negative underline underline-offset-2 hover:text-foreground"
          >
            Mode
          </a>{" "}
          page if needed.
        </span>
      </div>
    </div>
  );
}
