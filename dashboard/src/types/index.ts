// TypeScript interfaces matching backend Pydantic models.
// Field names use camelCase; the API client transforms snake_case responses.

export interface Position {
  symbol: string;
  secType: string;
  quantity: number;
  avgCost: number;
  currentPrice: number;
  unrealizedPnl: number;
  unrealizedPnlPct: number;
  marketValue: number;
}

export interface PortfolioSummary {
  totalMarketValue: number;
  totalUnrealizedPnl: number;
  totalRealizedPnl: number;
  netLiquidation: number;
}

export interface Greeks {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  symbol: string | null;
  isPortfolio: boolean;
}

export interface ReasoningStep {
  agent: string;
  reasoning: string | null;
  outputSummary: string | null;
  durationMs: number | null;
}

export interface TradeHistoryItem {
  orderId: string;
  symbol: string;
  action: string;
  quantity: number;
  fillPrice: number | null;
  commission: number | null;
  createdAt: string;
  updatedAt: string;
  reasoningChain: ReasoningStep[] | null;
}

export interface HealthStatus {
  ibConnected: boolean;
  dbConnected: boolean;
  redisConnected: boolean;
  dataFreshness: Record<string, number>;
  lastHeartbeat: string | null;
  pipelineStatus: string;
  agentLastSeen: Record<string, string>;
}

export interface ScenarioRequest {
  underlyingChangePct: number;
  ivChangePct: number;
  daysForward: number;
  riskFreeRate: number;
}

export interface ScenarioPositionResult {
  symbol?: string;
  right?: string;
  strike?: number;
  dte?: number;
  quantity?: number;
  currentPrice?: number;
  scenarioPrice?: number;
  currentValue?: number;
  scenarioValue?: number;
  pnl?: number;
  status?: string;
  reason?: string;
}

export interface ScenarioResponse {
  currentValue: number;
  scenarioValue: number;
  pnl: number;
  pnlPercent: number;
  perPosition: ScenarioPositionResult[];
}

export interface ApprovalContext {
  symbol: string;
  strategyType: string;
  maxLoss: number;
  maxProfit: number;
  deltaImpact: number;
  thetaImpact: number;
  vegaImpact: number;
  timeoutMinutes: number;
  additional?: Record<string, unknown> | null;
}

export interface Approval {
  approvalId: string;
  status: string;
  context: ApprovalContext;
  requestedAt: string;
  timeoutAt: string;
  resolvedAt: string | null;
}

export interface WSMessage {
  type: string;
  channel: string | null;
  data: unknown;
}
