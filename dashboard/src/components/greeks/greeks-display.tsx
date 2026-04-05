"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useGreeksStore } from "@/stores/greeks-store";

/**
 * Color thresholds for Greek value severity indicators.
 *
 * Green: within safe range (normal operation).
 * Yellow: approaching risk limits (attention needed).
 * Red: beyond safe thresholds (risk limit proximity).
 */
function getGreekColor(
  name: string,
  value: number
): "text-green-400" | "text-yellow-400" | "text-red-400" {
  const abs = Math.abs(value);

  switch (name) {
    case "Delta":
      if (abs > 1000) return "text-red-400";
      if (abs > 500) return "text-yellow-400";
      return "text-green-400";
    case "Gamma":
      if (abs > 200) return "text-red-400";
      if (abs > 100) return "text-yellow-400";
      return "text-green-400";
    case "Theta":
      if (abs > 500) return "text-red-400";
      if (abs > 250) return "text-yellow-400";
      return "text-green-400";
    case "Vega":
      if (abs > 1000) return "text-red-400";
      if (abs > 500) return "text-yellow-400";
      return "text-green-400";
    default:
      return "text-green-400";
  }
}

/**
 * Status dot icon for Greek severity level.
 */
function StatusDot({ color }: { color: string }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${color.replace("text-", "bg-")}`}
    />
  );
}

/**
 * Single Greek metric card displaying name, value, and color indicator.
 */
function GreekCard({ name, value }: { name: string; value: number }) {
  const color = getGreekColor(name, value);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <StatusDot color={color} />
          {name}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className={`text-2xl font-mono font-semibold ${color}`}>
          {value.toFixed(2)}
        </p>
      </CardContent>
    </Card>
  );
}

/**
 * Portfolio Greeks display with 4 metric cards (delta, gamma, theta, vega).
 *
 * Reads from the Zustand greeks store which is populated by the greeks
 * page via polling and WebSocket updates.
 */
export function GreeksDisplay() {
  const portfolioGreeks = useGreeksStore((s) => s.portfolioGreeks);

  if (!portfolioGreeks) {
    return (
      <div className="grid grid-cols-2 gap-4">
        {["Delta", "Gamma", "Theta", "Vega"].map((name) => (
          <Card key={name}>
            <CardHeader>
              <CardTitle className="text-sm">{name}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground text-sm">Awaiting data...</p>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4">
      <GreekCard name="Delta" value={portfolioGreeks.delta} />
      <GreekCard name="Gamma" value={portfolioGreeks.gamma} />
      <GreekCard name="Theta" value={portfolioGreeks.theta} />
      <GreekCard name="Vega" value={portfolioGreeks.vega} />
    </div>
  );
}
