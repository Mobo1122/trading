"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

/**
 * Preset scenario configurations for common what-if analyses.
 */
const PRESETS = [
  {
    label: "Market Crash (-10%)",
    underlyingChangePct: -10,
    ivChangePct: 50,
    daysForward: 0,
  },
  {
    label: "Rally (+5%)",
    underlyingChangePct: 5,
    ivChangePct: -10,
    daysForward: 0,
  },
  {
    label: "IV Crush (-30%)",
    underlyingChangePct: 0,
    ivChangePct: -30,
    daysForward: 0,
  },
  {
    label: "1 Week Theta",
    underlyingChangePct: 0,
    ivChangePct: 0,
    daysForward: 7,
  },
] as const;

interface ScenarioFormProps {
  onSubmit: (params: {
    underlyingChangePct: number;
    ivChangePct: number;
    daysForward: number;
  }) => void;
  loading: boolean;
}

/**
 * Scenario analysis input form with sliders and preset buttons.
 *
 * Provides controls for underlying price change (%), IV change (%),
 * and days forward. Preset buttons populate common scenarios for
 * quick analysis.
 */
export function ScenarioForm({ onSubmit, loading }: ScenarioFormProps) {
  const [underlyingChangePct, setUnderlyingChangePct] = useState(0);
  const [ivChangePct, setIvChangePct] = useState(0);
  const [daysForward, setDaysForward] = useState(0);

  function handlePreset(preset: (typeof PRESETS)[number]) {
    setUnderlyingChangePct(preset.underlyingChangePct);
    setIvChangePct(preset.ivChangePct);
    setDaysForward(preset.daysForward);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSubmit({ underlyingChangePct, ivChangePct, daysForward });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm text-muted-foreground">
          Scenario Parameters
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Preset buttons */}
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((preset) => (
              <Button
                key={preset.label}
                type="button"
                variant="outline"
                size="sm"
                onClick={() => handlePreset(preset)}
              >
                {preset.label}
              </Button>
            ))}
          </div>

          {/* Underlying Price Change */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label
                htmlFor="underlying-change"
                className="text-sm font-medium"
              >
                Underlying Price Change
              </label>
              <span className="text-sm font-mono text-muted-foreground">
                {underlyingChangePct > 0 ? "+" : ""}
                {underlyingChangePct}%
              </span>
            </div>
            <input
              id="underlying-change"
              type="range"
              min={-30}
              max={30}
              step={0.5}
              value={underlyingChangePct}
              onChange={(e) =>
                setUnderlyingChangePct(parseFloat(e.target.value))
              }
              className="w-full accent-primary"
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>-30%</span>
              <span>0%</span>
              <span>+30%</span>
            </div>
          </div>

          {/* IV Change */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label htmlFor="iv-change" className="text-sm font-medium">
                IV Change
              </label>
              <span className="text-sm font-mono text-muted-foreground">
                {ivChangePct > 0 ? "+" : ""}
                {ivChangePct}%
              </span>
            </div>
            <input
              id="iv-change"
              type="range"
              min={-50}
              max={100}
              step={1}
              value={ivChangePct}
              onChange={(e) => setIvChangePct(parseFloat(e.target.value))}
              className="w-full accent-primary"
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>-50%</span>
              <span>0%</span>
              <span>+100%</span>
            </div>
          </div>

          {/* Days Forward */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label htmlFor="days-forward" className="text-sm font-medium">
                Days Forward
              </label>
              <span className="text-sm font-mono text-muted-foreground">
                {daysForward} {daysForward === 1 ? "day" : "days"}
              </span>
            </div>
            <input
              id="days-forward"
              type="range"
              min={0}
              max={60}
              step={1}
              value={daysForward}
              onChange={(e) => setDaysForward(parseInt(e.target.value, 10))}
              className="w-full accent-primary"
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>0</span>
              <span>30</span>
              <span>60</span>
            </div>
          </div>

          <Button type="submit" disabled={loading} className="w-full">
            {loading ? "Calculating..." : "Run Scenario"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
