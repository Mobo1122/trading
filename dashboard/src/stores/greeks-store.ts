import { create } from "zustand";
import type { Greeks } from "@/types";

interface GreeksState {
  portfolioGreeks: Greeks | null;
  positionGreeks: Record<string, Greeks>;

  // Actions
  setPortfolioGreeks: (greeks: Greeks) => void;
  updatePositionGreeks: (symbol: string, greeks: Greeks) => void;
}

export const useGreeksStore = create<GreeksState>((set) => ({
  portfolioGreeks: null,
  positionGreeks: {},

  setPortfolioGreeks: (greeks) => set({ portfolioGreeks: greeks }),

  updatePositionGreeks: (symbol, greeks) =>
    set((state) => ({
      positionGreeks: { ...state.positionGreeks, [symbol]: greeks },
    })),
}));
