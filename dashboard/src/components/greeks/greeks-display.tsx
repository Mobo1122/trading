"use client";

import { useGreeksStore } from "@/stores/greeks-store";

/**
 * Greek severity tier — three signal colors instead of green/yellow/red.
 *
 *   nominal  → cyan (machine)  — within safe range
 *   warning  → amber (accent)  — approaching limits
 *   critical → magenta (negative) — beyond thresholds
 */
type Tier = "nominal" | "warning" | "critical";

function getGreekTier(name: string, value: number): Tier {
  const abs = Math.abs(value);
  switch (name) {
    case "Delta":
      if (abs > 1000) return "critical";
      if (abs > 500) return "warning";
      return "nominal";
    case "Gamma":
      if (abs > 200) return "critical";
      if (abs > 100) return "warning";
      return "nominal";
    case "Theta":
      if (abs > 500) return "critical";
      if (abs > 250) return "warning";
      return "nominal";
    case "Vega":
      if (abs > 1000) return "critical";
      if (abs > 500) return "warning";
      return "nominal";
    default:
      return "nominal";
  }
}

const TIER_DOT: Record<Tier, string> = {
  nominal: "bg-machine",
  warning: "bg-accent",
  critical: "bg-negative",
};

const TIER_TEXT: Record<Tier, string> = {
  nominal: "text-machine",
  warning: "text-accent",
  critical: "text-negative",
};

const TIER_LABEL: Record<Tier, string> = {
  nominal: "Nominal",
  warning: "Warning",
  critical: "Critical",
};

/**
 * Editorial Greek panel: tracked-out label, oversize tabular value,
 * status dot + tier label below. Four panels across, separated by
 * hairline rules.
 */
function GreekPanel({
  name,
  value,
  isLast,
}: {
  name: string;
  value: number | null;
  isLast: boolean;
}) {
  const tier = value == null ? "nominal" : getGreekTier(name, value);
  const display = value == null ? "—" : value.toFixed(2);

  return (
    <div
      className={`flex flex-col justify-between gap-6 px-6 py-7 ${
        isLast ? "" : "lg:border-r lg:border-rule"
      } border-b border-rule lg:border-b-0`}
    >
      <div>
        <div className="eyebrow">{name}</div>
        <div
          className={`mt-3 font-mono tabular-nums tracking-tight text-[40px] sm:text-[48px] leading-none ${TIER_TEXT[tier]}`}
        >
          {display}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className={`h-1.5 w-1.5 ${TIER_DOT[tier]}`} aria-hidden />
        <span className="eyebrow text-muted-foreground">
          {TIER_LABEL[tier]}
        </span>
      </div>
    </div>
  );
}

export function GreeksDisplay() {
  const portfolioGreeks = useGreeksStore((s) => s.portfolioGreeks);

  const greeks: { name: string; value: number | null }[] = [
    { name: "Delta", value: portfolioGreeks?.delta ?? null },
    { name: "Gamma", value: portfolioGreeks?.gamma ?? null },
    { name: "Theta", value: portfolioGreeks?.theta ?? null },
    { name: "Vega", value: portfolioGreeks?.vega ?? null },
  ];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 border border-rule">
      {greeks.map((g, i) => (
        <GreekPanel
          key={g.name}
          name={g.name}
          value={g.value}
          isLast={i === greeks.length - 1}
        />
      ))}
    </div>
  );
}
