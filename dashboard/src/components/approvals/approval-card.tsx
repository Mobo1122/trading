"use client";

import { useEffect, useState } from "react";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { TradeContext } from "@/components/approvals/trade-context";
import type { Approval } from "@/types";

/**
 * Individual approval card with trade context display and action buttons.
 *
 * Shows the trade details, a live countdown timer to timeout, and
 * Approve/Reject buttons. Buttons are disabled after click to prevent
 * double-submission. Resolved approvals show a status badge instead.
 */
export function ApprovalCard({
  approval,
  onResolve,
}: {
  approval: Approval;
  onResolve: (id: string, decision: "approved" | "rejected") => void;
}) {
  const [resolving, setResolving] = useState(false);
  const [remainingSeconds, setRemainingSeconds] = useState<number>(0);

  // Calculate and update countdown timer
  useEffect(() => {
    function calcRemaining(): number {
      const timeoutAt = new Date(approval.timeoutAt).getTime();
      const now = Date.now();
      return Math.max(0, Math.floor((timeoutAt - now) / 1000));
    }

    setRemainingSeconds(calcRemaining());

    const interval = setInterval(() => {
      setRemainingSeconds(calcRemaining());
    }, 1000);

    return () => clearInterval(interval);
  }, [approval.timeoutAt]);

  const isPending = approval.status === "pending";
  const isExpired = remainingSeconds <= 0 && isPending;

  function formatCountdown(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }

  function handleApprove() {
    setResolving(true);
    onResolve(approval.approvalId, "approved");
  }

  function handleReject() {
    setResolving(true);
    onResolve(approval.approvalId, "rejected");
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Trade Approval Required</span>
          <span className="text-base font-semibold">
            {approval.context.symbol}
          </span>
        </CardTitle>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            Requested:{" "}
            {new Date(approval.requestedAt).toLocaleTimeString()}
          </span>
          {isPending && !isExpired && (
            <span
              className={`tnum font-medium ${
                remainingSeconds < 60 ? "text-negative" : "text-muted-foreground"
              }`}
            >
              {formatCountdown(remainingSeconds)} remaining
            </span>
          )}
          {isExpired && (
            <Badge variant="secondary">Expired</Badge>
          )}
          {!isPending && (
            <Badge
              variant={
                approval.status === "approved"
                  ? "default"
                  : approval.status === "rejected"
                    ? "destructive"
                    : "secondary"
              }
            >
              {approval.status === "approved"
                ? "Approved"
                : approval.status === "rejected"
                  ? "Rejected"
                  : "Timed Out"}
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent>
        <TradeContext context={approval.context} />
      </CardContent>

      {isPending && !isExpired && (
        <CardFooter className="gap-2">
          <Button
            onClick={handleApprove}
            disabled={resolving}
            className="flex-1 bg-accent text-accent-foreground hover:bg-accent/85 tracking-[0.18em] uppercase text-[11px]"
          >
            {resolving ? "Resolving" : "Approve"}
          </Button>
          <Button
            onClick={handleReject}
            disabled={resolving}
            className="flex-1 bg-transparent border border-rule text-foreground hover:border-negative hover:text-negative tracking-[0.18em] uppercase text-[11px]"
          >
            {resolving ? "Resolving" : "Reject"}
          </Button>
        </CardFooter>
      )}
    </Card>
  );
}
