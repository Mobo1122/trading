"use client";

import { useEffect } from "react";
import { dashboardWS } from "@/lib/ws-client";

/**
 * Hook that manages the WebSocket connection lifecycle.
 * Connects on mount and disconnects on unmount.
 * Returns the singleton DashboardWebSocket instance for subscribe/unsubscribe.
 */
export function useWebSocket() {
  useEffect(() => {
    dashboardWS.connect();
    return () => {
      dashboardWS.disconnect();
    };
  }, []);

  return dashboardWS;
}
