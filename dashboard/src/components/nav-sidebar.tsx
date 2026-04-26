"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useApprovalsStore } from "@/stores/approvals-store";

/**
 * Brutalist mono sidebar with numbered nav items.
 *
 * Each item gets a 2-digit prefix and tracked-out caps. Active item
 * gets an amber leading bar; pending approvals show a magenta count
 * pip on the Approvals row.
 */

type NavItem = { href: string; label: string; n: string };

const NAV_ITEMS: readonly NavItem[] = [
  { n: "01", href: "/positions", label: "Positions" },
  { n: "02", href: "/greeks", label: "Greeks" },
  { n: "03", href: "/trades", label: "Trades" },
  { n: "04", href: "/approvals", label: "Approvals" },
  { n: "05", href: "/health", label: "Health" },
  { n: "06", href: "/scenarios", label: "Scenarios" },
  { n: "07", href: "/mode", label: "Mode" },
] as const;

export function NavSidebar() {
  const pathname = usePathname();
  const pendingCount = useApprovalsStore((s) => s.approvals.length);

  return (
    <nav className="sticky top-9 self-start flex h-[calc(100vh-2.25rem)] flex-col">
      {/* eyebrow header */}
      <div className="px-4 pt-6 pb-5">
        <div className="eyebrow text-muted-foreground">Console</div>
        <div className="mt-1 text-[11px] tracking-[0.18em] uppercase text-foreground">
          Mobo · DUP276229
        </div>
      </div>

      {/* nav links */}
      <ul className="flex-1">
        {NAV_ITEMS.map((item) => {
          const active =
            pathname === item.href || pathname?.startsWith(`${item.href}/`);
          const showPip = item.href === "/approvals" && pendingCount > 0;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                className={`group relative flex items-center gap-3 px-4 py-2.5 text-[11px] tracking-[0.18em] uppercase transition-colors ${
                  active
                    ? "text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {/* leading rule indicator */}
                <span
                  aria-hidden
                  className={`absolute left-0 top-0 h-full w-[2px] transition-colors ${
                    active ? "bg-accent" : "bg-transparent group-hover:bg-rule"
                  }`}
                />
                <span className="text-[10px] text-rule tabular-nums">
                  {item.n}
                </span>
                <span className="flex-1">{item.label}</span>
                {showPip && (
                  <span className="ml-auto inline-flex h-4 min-w-4 items-center justify-center bg-negative px-1 text-[9px] font-medium tabular-nums text-black">
                    {pendingCount}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>

      {/* bottom signature block */}
      <div className="border-t border-rule px-4 py-4 space-y-1.5">
        <div className="eyebrow">Watchlist</div>
        <div className="flex flex-wrap gap-x-2 gap-y-1 text-[10px] text-muted-foreground tracking-[0.1em]">
          <span>SPY</span>
          <span className="text-rule">·</span>
          <span>QQQ</span>
          <span className="text-rule">·</span>
          <span>IWM</span>
          <span className="text-rule">·</span>
          <span>AAPL</span>
          <span className="text-rule">·</span>
          <span>MSFT</span>
        </div>
      </div>
    </nav>
  );
}
