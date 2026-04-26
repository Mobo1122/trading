"use client";

import { useCallback, useEffect, useState } from "react";

import { PageHeader, PageMeta } from "@/components/operator/page-header";
import { getMode, switchMode, type ModeStatus } from "@/lib/api";

type SwitchPhase =
  | { kind: "idle" }
  | { kind: "type"; target: "paper" | "live"; entry: string }
  | { kind: "confirm"; target: "paper" | "live" }
  | { kind: "submitting"; target: "paper" | "live" }
  | { kind: "restarting"; target: "paper" | "live"; since: number }
  | { kind: "error"; message: string };

export default function ModePage() {
  const [status, setStatus] = useState<ModeStatus | null>(null);
  const [phase, setPhase] = useState<SwitchPhase>({ kind: "idle" });

  const refreshMode = useCallback(async () => {
    try {
      const data = await getMode();
      setStatus(data);
    } catch {
      /* keep last-known status */
    }
  }, []);

  useEffect(() => {
    refreshMode();
    const id = setInterval(refreshMode, 5_000);
    return () => clearInterval(id);
  }, [refreshMode]);

  const startSwitch = (target: "paper" | "live") => {
    setPhase({ kind: "type", target, entry: "" });
  };

  const submitSwitch = async (target: "paper" | "live") => {
    setPhase({ kind: "submitting", target });
    try {
      await switchMode(target);
      setPhase({ kind: "restarting", target, since: Date.now() });
    } catch (e) {
      setPhase({
        kind: "error",
        message: e instanceof Error ? e.message : "Switch failed",
      });
    }
  };

  const isLive = status?.runtimeMode === "live";
  const targetMode: "paper" | "live" = isLive ? "paper" : "live";

  return (
    <div className="rise px-8 sm:px-10 py-10 max-w-[1280px]">
      <PageHeader
        number="07"
        section="Operator Lever"
        title="Trading Mode"
        lede="The single most consequential switch in the system. Flipping this commits real capital to whatever the agents decide. Flip with care."
        meta={
          status && (
            <PageMeta
              label="Persisted Mode"
              value={status.fileMode ?? "unknown"}
            />
          )
        }
      />

      {!status ? (
        <div className="mt-10 border border-rule px-6 py-16 text-center">
          <div className="eyebrow caret">Probing</div>
        </div>
      ) : (
        <div className="mt-10 space-y-12">
          {/* Current mode display */}
          <CurrentMode status={status} />

          {/* Switch action */}
          {phase.kind === "idle" && status.canSwitch && (
            <SwitchAction
              currentMode={status.runtimeMode}
              targetMode={targetMode}
              onClick={() => startSwitch(targetMode)}
            />
          )}

          {phase.kind === "idle" && !status.canSwitch && (
            <div className="border border-rule px-6 py-8">
              <div className="eyebrow text-negative">Switching Disabled</div>
              <p className="mt-3 text-sm text-muted-foreground max-w-xl">
                {status.reason ??
                  "Mode switching is not wired up in this deployment."}
              </p>
            </div>
          )}

          {phase.kind === "type" && (
            <TypeConfirm
              target={phase.target}
              entry={phase.entry}
              onChange={(entry) =>
                setPhase({ kind: "type", target: phase.target, entry })
              }
              onSubmit={() =>
                setPhase({ kind: "confirm", target: phase.target })
              }
              onCancel={() => setPhase({ kind: "idle" })}
            />
          )}

          {phase.kind === "confirm" && (
            <FinalConfirm
              target={phase.target}
              onSubmit={() => submitSwitch(phase.target)}
              onCancel={() => setPhase({ kind: "idle" })}
            />
          )}

          {phase.kind === "submitting" && (
            <div className="border border-accent/40 px-6 py-8">
              <div className="eyebrow text-accent caret">Submitting</div>
              <p className="mt-3 text-sm text-muted-foreground">
                Updating .env and triggering container restart…
              </p>
            </div>
          )}

          {phase.kind === "restarting" && (
            <RestartingPanel
              target={phase.target}
              since={phase.since}
              onCancel={() => {
                setPhase({ kind: "idle" });
                refreshMode();
              }}
            />
          )}

          {phase.kind === "error" && (
            <div className="border border-negative/50 bg-negative/5 px-6 py-8">
              <div className="eyebrow text-negative">Switch Failed</div>
              <p className="mt-3 text-sm text-negative">{phase.message}</p>
              <button
                onClick={() => setPhase({ kind: "idle" })}
                className="mt-4 border border-rule px-4 py-2 text-[11px] tracking-[0.18em] uppercase hover:border-foreground hover:text-foreground"
              >
                Dismiss
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CurrentMode({ status }: { status: ModeStatus }) {
  const isLive = status.runtimeMode === "live";
  return (
    <div className="border-y border-rule py-10">
      <div className="eyebrow">Current Runtime Mode</div>
      <div
        className={`mt-3 font-display text-[80px] sm:text-[96px] leading-none tracking-tight ${
          isLive ? "text-negative" : "text-accent"
        }`}
      >
        {status.runtimeMode.toUpperCase()}
        <span
          className={`ml-4 inline-block h-4 w-4 align-middle ${
            isLive ? "bg-negative" : "bg-accent"
          } pulse`}
          aria-hidden
        />
      </div>
      <p className="mt-4 max-w-2xl text-xs text-muted-foreground">
        {isLive
          ? "Real orders are flowing to your IBKR live account. Every trade the agents place is using real capital."
          : "Trades are simulated. The IBKR paper account never touches real money. Use this mode to validate the system."}
      </p>
    </div>
  );
}

function SwitchAction({
  currentMode,
  targetMode,
  onClick,
}: {
  currentMode: "paper" | "live";
  targetMode: "paper" | "live";
  onClick: () => void;
}) {
  const goingLive = targetMode === "live";
  return (
    <div className="border border-rule px-6 py-8">
      <div className="flex items-start justify-between gap-6">
        <div>
          <div className="eyebrow">Switch Action</div>
          <p className="mt-3 max-w-xl font-display italic text-[18px] leading-snug text-muted-foreground">
            {goingLive
              ? "Flip from paper to live. The trading engine and IB Gateway will restart and reconnect to the live account."
              : "Flip from live back to paper. Pending live orders are not cancelled — manage them via IBKR before flipping."}
          </p>
        </div>
        <button
          onClick={onClick}
          className={`shrink-0 px-6 py-3 text-[11px] tracking-[0.18em] uppercase border ${
            goingLive
              ? "border-negative text-negative hover:bg-negative hover:text-black"
              : "border-accent text-accent hover:bg-accent hover:text-black"
          }`}
        >
          → Switch to {targetMode}
        </button>
      </div>
      <p className="mt-6 text-[10px] tracking-[0.16em] uppercase text-muted-foreground">
        Currently in {currentMode}. Two confirmations required to proceed.
      </p>
    </div>
  );
}

function TypeConfirm({
  target,
  entry,
  onChange,
  onSubmit,
  onCancel,
}: {
  target: "paper" | "live";
  entry: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  const expected = target.toUpperCase();
  const matches = entry === expected;
  return (
    <div className="border border-rule px-6 py-8">
      <div className="eyebrow">Step 1 — Type to Confirm</div>
      <p className="mt-3 max-w-xl text-sm text-muted-foreground">
        To switch to <span className="text-foreground">{target}</span> mode,
        type the word{" "}
        <span className="text-accent font-medium">{expected}</span> exactly
        into the box below.
      </p>
      <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-center">
        <input
          type="text"
          autoFocus
          value={entry}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          onKeyDown={(e) => {
            if (e.key === "Enter" && matches) onSubmit();
            if (e.key === "Escape") onCancel();
          }}
          spellCheck={false}
          autoCorrect="off"
          className="w-full sm:w-72 bg-black border border-rule px-4 py-3 font-mono text-lg tracking-[0.2em] uppercase text-foreground focus:border-accent focus:outline-none"
          placeholder={expected}
        />
        <div className="flex gap-2">
          <button
            disabled={!matches}
            onClick={onSubmit}
            className="px-5 py-3 text-[11px] tracking-[0.18em] uppercase border border-accent text-accent hover:bg-accent hover:text-black disabled:border-rule disabled:text-rule disabled:hover:bg-transparent disabled:cursor-not-allowed"
          >
            Continue
          </button>
          <button
            onClick={onCancel}
            className="px-5 py-3 text-[11px] tracking-[0.18em] uppercase border border-rule text-muted-foreground hover:border-foreground hover:text-foreground"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function FinalConfirm({
  target,
  onSubmit,
  onCancel,
}: {
  target: "paper" | "live";
  onSubmit: () => void;
  onCancel: () => void;
}) {
  const goingLive = target === "live";
  return (
    <div
      className={`border ${
        goingLive ? "border-negative" : "border-accent"
      } px-6 py-8`}
    >
      <div
        className={`eyebrow ${goingLive ? "text-negative" : "text-accent"}`}
      >
        Step 2 — Final Confirmation
      </div>
      <p className="mt-3 max-w-2xl font-display italic text-[20px] leading-snug">
        {goingLive
          ? "You are about to commit real capital to autonomous AI agents. Are you certain you've validated the system in paper mode and accepted the risk?"
          : "You are about to halt live trading. The trading engine and IB Gateway will restart in paper mode."}
      </p>
      <div className="mt-6 flex gap-2">
        <button
          onClick={onSubmit}
          className={`px-6 py-3 text-[11px] tracking-[0.18em] uppercase ${
            goingLive
              ? "bg-negative text-black hover:bg-negative/85"
              : "bg-accent text-black hover:bg-accent/85"
          }`}
        >
          Yes — Switch to {target}
        </button>
        <button
          onClick={onCancel}
          className="px-5 py-3 text-[11px] tracking-[0.18em] uppercase border border-rule text-muted-foreground hover:border-foreground hover:text-foreground"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function RestartingPanel({
  target,
  since,
  onCancel,
}: {
  target: "paper" | "live";
  since: number;
  onCancel: () => void;
}) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const id = setInterval(
      () => setElapsed(Math.floor((Date.now() - since) / 1000)),
      1000
    );
    return () => clearInterval(id);
  }, [since]);

  return (
    <div className="border border-accent/50 px-6 py-8">
      <div className="eyebrow text-accent caret">Restart In Progress</div>
      <p className="mt-3 max-w-2xl text-sm text-muted-foreground">
        The trading engine and IB Gateway are restarting in{" "}
        <span className="text-foreground">{target}</span> mode. The status
        bar at the top of the screen will reflect the new mode within ~60
        seconds once the IB session is established.
      </p>
      <div className="mt-6 flex items-center gap-6">
        <div className="tnum text-[24px] text-foreground">
          {elapsed}s elapsed
        </div>
        <button
          onClick={onCancel}
          className="px-5 py-2 text-[11px] tracking-[0.18em] uppercase border border-rule text-muted-foreground hover:border-foreground hover:text-foreground"
        >
          Done
        </button>
      </div>
    </div>
  );
}
