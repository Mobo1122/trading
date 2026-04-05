"use client";

import { useWebSocket } from "@/hooks/use-websocket";

/**
 * Client component that establishes the WebSocket connection.
 *
 * Imported by the root Server Component layout to isolate the
 * "use client" boundary. The connection persists across page
 * navigations because this component lives in the root layout.
 */
export function WsProvider({ children }: { children: React.ReactNode }) {
  useWebSocket();
  return <>{children}</>;
}
