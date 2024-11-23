/*
 * Client-page injected utilities for reloading in response
 * to a development server.
 */
import { useEffect } from "react";

interface CustomProcess {
  env: {
    LIVE_RELOAD_PORT?: string;
    NODE_ENV?: string;
    SSR_RENDERING?: boolean;
  };
}

// Stub variable for typechecking the build-time variable insertion
declare var process: CustomProcess;

class ReconnectWebSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private protocols?: string | string[];
  private reconnectInterval = 1000; // Initial reconnect interval.
  private maxReconnectInterval = 15000; // Maximum reconnect interval.
  private reconnectDecay = 1.5; // Rate of increase of the reconnect delay.
  private reconnectAttempts = 0; // Counter for reconnect attempts.
  private forcedClose = false; // Indicates if the close was intentional.
  private messageQueue: any[] = []; // Queue of messages to be sent once the connection is re-established.

  // Event handlers
  public onopen: ((event: Event) => void) | null = null;
  public onclose: ((event: CloseEvent) => void) | null = null;
  public onmessage: ((event: MessageEvent) => void) | null = null;
  public onerror: ((event: Event) => void) | null = null;

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols;
    this.connect(false); // Initial connection attempt
  }

  private connect(reconnectAttempt: boolean): void {
    if (reconnectAttempt) {
      // Delay using exponential backoff, up until our max interval.
      const delay = Math.min(
        this.reconnectInterval *
          Math.pow(this.reconnectDecay, this.reconnectAttempts),
        this.maxReconnectInterval,
      );
      setTimeout(() => this.establishConnection(), delay);
    } else {
      this.establishConnection();
    }
  }

  private establishConnection(): void {
    console.debug("Attempting WebSocket connection...");
    this.ws = new WebSocket(this.url, this.protocols);

    this.ws.onopen = (event) => {
      this.onReconnectSuccess(event);
    };

    this.ws.onmessage = (event) => {
      if (this.onmessage) this.onmessage(event);
    };

    this.ws.onerror = (event) => {
      if (this.onerror) this.onerror(event);
    };

    this.ws.onclose = (event) => {
      this.onReconnectClose(event);
    };
  }

  private onReconnectSuccess(event: Event): void {
    console.log("WebSocket connected.");
    this.reconnectAttempts = 0;
    if (this.onopen) this.onopen(event);
    this.messageQueue.forEach((message) => this.send(message));
    this.messageQueue = [];
  }

  private onReconnectClose(event: CloseEvent): void {
    this.ws = null;
    if (!this.forcedClose) {
      this.reconnectAttempts++;
      this.connect(true); // Attempt to reconnect
    }
    if (this.onclose) this.onclose(event);
  }

  public send(data: any): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(data);
    } else {
      this.messageQueue.push(data);
    }
  }

  public close(): void {
    if (this.ws) {
      this.forcedClose = true;
      this.ws.close();
    }
  }

  public get readyState(): number {
    return this.ws ? this.ws.readyState : WebSocket.CLOSED;
  }
}

const mountLiveReload = ({ host, port }: { host?: string; port?: number }) => {
  // Noop if we're not in development mode
  if (
    process.env.SSR_RENDERING === true ||
    process.env.NODE_ENV !== "development"
  ) {
    return;
  }

  if (!host) host = "localhost";
  if (!port) {
    if (!process.env.LIVE_RELOAD_PORT) {
      console.error(
        "process.env.LIVE_RELOAD_PORT is not passed from server to development client.",
      );
      return;
    }
    port = Number(process.env.LIVE_RELOAD_PORT);
  }

  useEffect(() => {
    console.log("Connecting to live reload server...");
    const ws = new ReconnectWebSocket(`ws://${host}:${port}/build-events`);
    ws.onmessage = () => {
      // Right now we use a hard-refresh strategy for all events
      window.location.reload();
    };
    ws.onerror = (event) => {
      console.error("WebSocket error:", event);
    };
  }, []);
};

export default mountLiveReload;
