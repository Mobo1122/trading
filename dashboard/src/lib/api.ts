import type {
  Approval,
  Position,
  PortfolioSummary,
  Greeks,
  TradeHistoryItem,
  HealthStatus,
  ScenarioRequest,
  ScenarioResponse,
} from "@/types";

function resolveApiUrl(): string {
  const explicit = process.env.NEXT_PUBLIC_API_URL;
  if (explicit) return explicit;
  // No explicit URL: use origin-relative (browser) or localhost fallback (SSR).
  if (typeof window !== "undefined") return "";
  return "http://localhost:8000";
}

const API_URL = resolveApiUrl();

/**
 * Recursively transform snake_case object keys to camelCase.
 */
function toCamelCase(str: string): string {
  return str.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase());
}

function transformKeys(obj: unknown): unknown {
  if (Array.isArray(obj)) {
    return obj.map(transformKeys);
  }
  if (obj !== null && typeof obj === "object") {
    const result: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
      result[toCamelCase(key)] = transformKeys(value);
    }
    return result;
  }
  return obj;
}

/**
 * Generic fetch helper that prepends API_URL, sets headers,
 * and transforms snake_case response keys to camelCase.
 */
async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_URL}${path}`;
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...options?.headers,
  };

  const response = await fetch(url, { ...options, headers });

  if (!response.ok) {
    const text = await response.text().catch(() => "Unknown error");
    throw new Error(`API error ${response.status}: ${text}`);
  }

  const data = await response.json();
  return transformKeys(data) as T;
}

// --- Convenience API functions ---

export async function getPositions(): Promise<Position[]> {
  return fetchApi<Position[]>("/api/positions");
}

export async function getPortfolio(): Promise<PortfolioSummary> {
  return fetchApi<PortfolioSummary>("/api/portfolio");
}

export async function getGreeks(): Promise<Greeks> {
  return fetchApi<Greeks>("/api/greeks");
}

export async function getTradeHistory(
  limit = 50,
  offset = 0
): Promise<{ trades: TradeHistoryItem[]; total: number }> {
  return fetchApi<{ trades: TradeHistoryItem[]; total: number }>(
    `/api/trades/history?limit=${limit}&offset=${offset}`
  );
}

export async function getHealth(): Promise<HealthStatus> {
  return fetchApi<HealthStatus>("/api/health/status");
}

export async function runScenario(
  request: ScenarioRequest
): Promise<ScenarioResponse> {
  return fetchApi<ScenarioResponse>("/api/scenarios", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export async function getPendingApprovals(): Promise<Approval[]> {
  return fetchApi<Approval[]>("/api/approvals/pending");
}

export async function resolveApproval(
  approvalId: string,
  decision: "approved" | "rejected"
): Promise<{ success: boolean }> {
  return fetchApi<{ success: boolean }>(
    `/api/approvals/${approvalId}/resolve`,
    {
      method: "POST",
      body: JSON.stringify({ decision }),
    }
  );
}
