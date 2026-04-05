"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/positions", label: "Positions" },
  { href: "/greeks", label: "Greeks" },
  { href: "/trades", label: "Trades" },
  { href: "/health", label: "Health" },
  { href: "/scenarios", label: "Scenarios" },
] as const;

/**
 * Sidebar navigation with active link highlighting.
 *
 * Client component because it reads the current pathname via usePathname().
 */
export function NavSidebar() {
  const pathname = usePathname();

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
                block rounded-md px-3 py-2 text-sm font-medium transition-colors
                ${
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground"
                }
              `}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
