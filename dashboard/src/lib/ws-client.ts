import { usePositionsStore } from "@/stores/positions-store";
import { useGreeksStore } from "@/stores/greeks-store";
import { useHealthStore } from "@/stores/health-store";
import type { WSMessage, Position, HealthStatus, Greeks } from "@/types";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";
const RECONNECT_DELAY = 3000;
const PING_INTERVAL = 30000;

const DEFAULT_CHANNELS = ["positions", "health", "portfolio_greeks"];

/**
 * WebSocket client for the trading dashboard.
 *
 * Connects to the FastAPI /ws endpoint, subscribes to channels,
 * auto-reconnects on disconnect, sends periodic pings, and routes
 * incoming messages directly to Zustand stores (outside React context).
 */
class DashboardWebSocket {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private isIntentionalClose = false;

  /**
   * Open a WebSocket connection and subscribe to default channels.
   */
  connect(): void {
    // Avoid duplicate connections
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN ||
        this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    this.isIntentionalClose = false;

    try {
      this.ws = new WebSocket(WS_URL);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      // Subscribe to default channels once connected
      for (const channel of DEFAULT_CHANNELS) {
        this.subscribe(channel);
      }
      this.startPing();
    };

    this.ws.onmessage = (event: MessageEvent) => {
      this.handleMessage(event);
    };

    this.ws.onclose = () => {
      this.stopPing();
      if (!this.isIntentionalClose) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      // Close triggers onclose which handles reconnect
      this.ws?.close();
    };
  }

  /**
   * Close the WebSocket connection intentionally (no auto-reconnect).
   */
  disconnect(): void {
    this.isIntentionalClose = true;
    this.clearReconnect();
    this.stopPing();
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  /**
   * Subscribe to a channel on the WebSocket server.
   */
  subscribe(channel: string): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: "subscribe", channel }));
    }
  }

  /**
   * Unsubscribe from a channel on the WebSocket server.
   */
  unsubscribe(channel: string): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: "unsubscribe", channel }));
    }
  }

  // --- Private helpers ---

  private handleMessage(event: MessageEvent): void {
    let msg: WSMessage;
    try {
      msg = JSON.parse(event.data as string) as WSMessage;
    } catch {
      return; // Ignore malformed messages
    }

    const { type, channel, data } = msg;

    if (type === "pong") {
      return; // Heartbeat response, no action needed
    }

    if (type === "snapshot" || type === "channel_snapshot") {
      this.handleSnapshot(channel, data);
      return;
    }

    if (type === "update") {
      this.handleUpdate(channel, data);
      return;
    }
  }

  private handleSnapshot(channel: string | null, data: unknown): void {
    if (!channel) return;

    if (channel === "positions") {
      usePositionsStore.getState().setPositions(data as Position[]);
    } else if (channel === "health") {
      useHealthStore.getState().setHealth(data as HealthStatus);
    } else if (channel === "portfolio_greeks") {
      useGreeksStore.getState().setPortfolioGreeks(data as Greeks);
    }
  }

  private handleUpdate(channel: string | null, data: unknown): void {
    if (!channel) return;

    if (channel === "positions") {
      usePositionsStore.getState().updatePosition(data as Position);
    } else if (channel === "health") {
      useHealthStore.getState().setHealth(data as HealthStatus);
    } else if (channel === "portfolio_greeks") {
      useGreeksStore.getState().setPortfolioGreeks(data as Greeks);
    } else if (channel.startsWith("quotes:")) {
      // Price update for a specific symbol -- update position price
      const priceData = data as { symbol: string; price: number };
      const store = usePositionsStore.getState();
      const existing = store.positions[priceData.symbol];
      if (existing) {
        store.updatePosition({
          ...existing,
          currentPrice: priceData.price,
        });
      }
    }
  }

  private startPing(): void {
    this.stopPing();
    this.pingTimer = setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: "ping" }));
      }
    }, PING_INTERVAL);
  }

  private stopPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private scheduleReconnect(): void {
    this.clearReconnect();
    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, RECONNECT_DELAY);
  }

  private clearReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}

/** Singleton WebSocket client instance for the dashboard. */
export const dashboardWS = new DashboardWebSocket();
