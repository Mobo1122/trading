"use client";

import { usePositionsStore } from "@/stores/positions-store";

/**
 * Editorial readouts: small tracked-out label, oversize tabular number.
 * Four columns separated by hairline rules — newspaper financial section
 * meets terminal aesthetic. Negative numbers in magenta, positives in
 * the amber signal color.
 */
export function PortfolioSummary() {
  const summary = usePositionsStore((state) => state.portfolioSummary);

  if (!summary) {
    return (
      <div className="border-y border-rule py-6 text-center text-xs text-muted-foreground">
        — no portfolio data yet —
      </div>
    );
  }

  const metrics = [
    {
      label: "Total Market Value",
      value: summary.totalMarketValue,
      signed: false,
    },
    {
      label: "Unrealized P&L",
      value: summary.totalUnrealizedPnl,
      signed: true,
    },
    {
      label: "Realized P&L",
      value: summary.totalRealizedPnl,
      signed: true,
    },
    { label: "Net Liquidation", value: summary.netLiquidation, signed: false },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 border-y border-rule">
      {metrics.map((m, i) => (
        <Readout
          key={m.label}
          label={m.label}
          value={m.value}
          signed={m.signed}
          isLastInRow={(i + 1) % 2 === 0}
          isLastInGrid={i === metrics.length - 1}
        />
      ))}
    </div>
  );
}

function Readout({
  label,
  value,
  signed,
  isLastInRow,
  isLastInGrid,
}: {
  label: string;
  value: number;
  signed: boolean;
  isLastInRow: boolean;
  isLastInGrid: boolean;
}) {
  const negative = signed && value < 0;
  const positive = signed && value > 0;

  // hairline rules between cells: vertical between cols, horizontal between rows on small screens
  const borderClasses = [
    "border-rule",
    !isLastInRow ? "sm:border-r" : "",
    !isLastInGrid ? "lg:border-r" : "",
    "lg:[&:last-child]:border-r-0",
  ].join(" ");

  return (
    <div className={`px-6 py-7 ${borderClasses}`}>
      <div className="eyebrow">{label}</div>
      <div
        className={`mt-3 font-mono tabular-nums tracking-tight text-[28px] sm:text-[32px] leading-none ${
          negative
            ? "text-negative"
            : positive
              ? "text-accent"
              : "text-foreground"
        }`}
      >
        {formatUSD(value, signed)}
      </div>
    </div>
  );
}

function formatUSD(v: number, signed: boolean): string {
  const abs = Math.abs(v);
  const formatted = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(abs);
  if (!signed) return formatted;
  if (v < 0) return `\u2212${formatted}`; // proper minus sign
  if (v > 0) return `+${formatted}`;
  return formatted;
}
