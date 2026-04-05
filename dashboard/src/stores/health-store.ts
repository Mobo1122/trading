import { create } from "zustand";
import type { HealthStatus } from "@/types";

interface HealthState {
  health: HealthStatus | null;
  lastUpdated: string | null;

  // Actions
  setHealth: (status: HealthStatus) => void;
}

export const useHealthStore = create<HealthState>((set) => ({
  health: null,
  lastUpdated: null,

  setHealth: (status) =>
    set({
      health: status,
      lastUpdated: new Date().toISOString(),
    }),
}));
