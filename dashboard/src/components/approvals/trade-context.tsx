import type { ApprovalContext } from "@/types";

/**
 * Displays trade context fields in a grid layout.
 *
 * Presentational component showing strategy details and Greeks impact
 * for an approval request. Max loss values exceeding $1000 are
 * highlighted in red to draw attention.
 */
export function TradeContext({ context }: { context: ApprovalContext }) {
  const rows = [
    { label: "Symbol", value: context.symbol },
    { label: "Strategy", value: context.strategyType },
    {
      label: "Max Loss",
      value: `$${context.maxLoss.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
      highlight: context.maxLoss > 1000,
    },
    {
      label: "Max Profit",
      value: `$${context.maxProfit.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
    },
    {
      label: "Delta Impact",
      value: context.deltaImpact.toFixed(2),
    },
    {
      label: "Theta Impact",
      value: context.thetaImpact.toFixed(2),
    },
    {
      label: "Vega Impact",
      value: context.vegaImpact.toFixed(2),
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
      {rows.map((row) => (
        <div key={row.label} className="contents">
          <span className="text-muted-foreground">{row.label}</span>
          <span
            className={`text-right tnum ${
              row.highlight ? "text-negative" : ""
            }`}
          >
            {row.value}
          </span>
        </div>
      ))}
    </div>
  );
}
