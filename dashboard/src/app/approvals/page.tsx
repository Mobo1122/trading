"use client";

import { useEffect } from "react";
import { useApprovalsStore } from "@/stores/approvals-store";
import { ApprovalCard } from "@/components/approvals/approval-card";
import { PageHeader, PageMeta } from "@/components/operator/page-header";
import { dashboardWS } from "@/lib/ws-client";

export default function ApprovalsPage() {
  const { approvals, loading, error, fetchApprovals, resolveApproval } =
    useApprovalsStore();

  useEffect(() => {
    fetchApprovals();
    dashboardWS.subscribe("approvals");
    return () => {
      dashboardWS.unsubscribe("approvals");
    };
  }, [fetchApprovals]);

  return (
    <div className="rise px-8 sm:px-10 py-10 max-w-[1280px]">
      <PageHeader
        number="04"
        section="Operator Gate"
        title="Pending Approvals"
        lede="Trades that exceed the auto-execution thresholds — they wait here for the operator to confirm or reject."
        meta={
          <PageMeta
            label="Queue"
            value={`${approvals.length} waiting`}
          />
        }
      />

      <div className="mt-10 space-y-6">
        {error && (
          <div className="border border-negative/40 bg-negative/5 px-5 py-4">
            <div className="eyebrow text-negative">Error</div>
            <p className="mt-2 text-xs text-negative">{error}</p>
          </div>
        )}

        {loading && approvals.length === 0 ? (
          <div className="border border-rule px-6 py-16 text-center">
            <div className="eyebrow caret">Loading</div>
          </div>
        ) : approvals.length === 0 && !error ? (
          <div className="border border-rule px-6 py-16 text-center">
            <div className="eyebrow">Queue Empty</div>
            <p className="mt-3 max-w-md mx-auto font-display italic text-[15px] leading-snug text-muted-foreground">
              No trades currently require operator review. Anything below the
              auto-execution thresholds is processed without a human in the
              loop.
            </p>
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            {approvals.map((approval) => (
              <ApprovalCard
                key={approval.approvalId}
                approval={approval}
                onResolve={resolveApproval}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
