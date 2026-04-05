import { create } from "zustand";
import type { Position, PortfolioSummary } from "@/types";

interface PositionsState {
  positions: Record<string, Position>;
  portfolioSummary: PortfolioSummary | null;

  // Actions
  updatePosition: (pos: Position) => void;
  setPositions: (positions: Position[]) => void;
  setPortfolioSummary: (summary: PortfolioSummary) => void;
}

export const usePositionsStore = create<PositionsState>((set) => ({
  positions: {},
  portfolioSummary: null,

  updatePosition: (pos) =>
    set((state) => {
      const updated = { ...state.positions, [pos.symbol]: pos };
      // Recalculate portfolio-level PnL from all positions
      const allPositions = Object.values(updated);
      const totalUnrealizedPnl = allPositions.reduce(
        (sum, p) => sum + p.unrealizedPnl,
        0
      );
      const totalMarketValue = allPositions.reduce(
        (sum, p) => sum + p.marketValue,
        0
      );
      return {
        positions: updated,
        portfolioSummary: state.portfolioSummary
          ? { ...state.portfolioSummary, totalUnrealizedPnl, totalMarketValue }
          : null,
      };
    }),

  setPositions: (positions) =>
    set(() => {
      const posMap: Record<string, Position> = {};
      for (const pos of positions) {
        posMap[pos.symbol] = pos;
      }
      return { positions: posMap };
    }),

  setPortfolioSummary: (summary) => set({ portfolioSummary: summary }),
}));
