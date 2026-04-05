import { create } from "zustand";
import { getPendingApprovals, resolveApproval } from "@/lib/api";
import type { Approval } from "@/types";

interface ApprovalsState {
  approvals: Approval[];
  loading: boolean;
  error: string | null;

  // Actions
  fetchApprovals: () => Promise<void>;
  resolveApproval: (
    approvalId: string,
    decision: "approved" | "rejected"
  ) => Promise<void>;
  updateFromWs: (data: unknown) => void;
}

export const useApprovalsStore = create<ApprovalsState>((set, get) => ({
  approvals: [],
  loading: false,
  error: null,

  fetchApprovals: async () => {
    set({ loading: true, error: null });
    try {
      const approvals = await getPendingApprovals();
      set({ approvals, loading: false });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to fetch";
      set({ error: message, loading: false });
    }
  },

  resolveApproval: async (approvalId, decision) => {
    try {
      await resolveApproval(approvalId, decision);
      // Re-fetch to get updated list
      await get().fetchApprovals();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to resolve";
      set({ error: message });
    }
  },

  updateFromWs: (_data: unknown) => {
    // On any approval WebSocket event, re-fetch the pending list.
    // This is the simplest approach -- avoids complex partial state
    // management for approval_request and approval_resolved events.
    get().fetchApprovals();
  },
}));
