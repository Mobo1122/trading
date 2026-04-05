"use client";

import { useEffect } from "react";
import { useApprovalsStore } from "@/stores/approvals-store";
import { ApprovalCard } from "@/components/approvals/approval-card";
import { dashboardWS } from "@/lib/ws-client";

/**
 * Approval queue page displaying pending trade approvals.
 *
 * Fetches pending approvals on mount, subscribes to the WebSocket
 * 'approvals' channel for real-time updates, and renders each
 * approval as an interactive card with approve/reject buttons.
 */
export default function ApprovalsPage() {
  const { approvals, loading, error, fetchApprovals, resolveApproval } =
    useApprovalsStore();

  useEffect(() => {
    fetchApprovals();

    // Subscribe to WebSocket approvals channel for real-time updates
    dashboardWS.subscribe("approvals");

    return () => {
      dashboardWS.unsubscribe("approvals");
    };
  }, [fetchApprovals]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">
          Pending Approvals
          {approvals.length > 0 && (
            <span className="ml-2 text-base font-normal text-muted-foreground">
              ({approvals.length})
            </span>
          )}
        </h1>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400">
          {error}
        </div>
      )}

      {loading && approvals.length === 0 && (
        <p className="text-muted-foreground">Loading approvals...</p>
      )}

      {!loading && approvals.length === 0 && !error && (
        <div className="rounded-md border border-dashed p-8 text-center text-muted-foreground">
          No pending approvals. Trades below auto-execute thresholds are
          processed automatically.
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        {approvals.map((approval) => (
          <ApprovalCard
            key={approval.approvalId}
            approval={approval}
            onResolve={resolveApproval}
          />
        ))}
      </div>
    </div>
  );
}
