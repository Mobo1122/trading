"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useApprovalsStore } from "@/stores/approvals-store";

const NAV_ITEMS = [
  { href: "/positions", label: "Positions" },
  { href: "/greeks", label: "Greeks" },
  { href: "/trades", label: "Trades" },
  { href: "/approvals", label: "Approvals" },
  { href: "/health", label: "Health" },
  { href: "/scenarios", label: "Scenarios" },
] as const;

/**
 * Sidebar navigation with active link highlighting.
 *
 * Client component because it reads the current pathname via usePathname()
 * and the approvals store for the pending count badge.
 */
export function NavSidebar() {
  const pathname = usePathname();
  const pendingCount = useApprovalsStore((s) => s.approvals.length);

  return (
    <nav className="w-[240px] border-r bg-card p-4 space-y-2">
      <div className="mb-6">
        <h2 className="text-lg font-semibold tracking-tight">
          Trading Dashboard
        </h2>
        <p className="text-xs text-muted-foreground">Real-time monitoring</p>
      </div>

      <div className="space-y-1">
        {NAV_ITEMS.map((item) => {
          const isActive =
            pathname === item.href || pathname?.startsWith(`${item.href}/`);

          return (
            <Link
              key={item.href}
              href={item.href}
              className={`
                flex items-center justify-between rounded-md px-3 py-2 text-sm font-medium transition-colors
                ${
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground"
                }
              `}
            >
              <span>{item.label}</span>
              {item.href === "/approvals" && pendingCount > 0 && (
                <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1.5 text-xs font-medium text-primary-foreground">
                  {pendingCount}
                </span>
              )}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
