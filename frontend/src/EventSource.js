// EventSource management module
export class EventSourceManager {
  constructor() {
    this.eventSource = null;
    this.updateQueue = new Map();
    this.debounceTimer = null;
    this.debounceDelay = 50; // 50ms debounce for faster updates
  }

  connect(onMessage) {
    // Close any existing connection
    if (this.eventSource) {
      this.eventSource.close();
    }

    // Save the last onMessage callback (for reconnection)
    this.lastOnMessage = onMessage;

    this.eventSource = new EventSource("/api/events");

    this.eventSource.onopen = () => {
      console.log("EventSource connected");
      this.reconnectAttempts = 0; // Reset retry count on successful connection
    };

    this.eventSource.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        
        // heartbeat and connection messages are used only to check connection status
        if (message.type === "heartbeat") {
          console.log("💓 SSE heartbeat received", message.queue_size ? `(queue: ${message.queue_size})` : "");
          return;
        }
        
        if (message.type === "connection") {
          console.log("🔌 SSE connection established:", message.status);
          return;
        }

        // Important messages are handled immediately
        if (message.type === "force_refresh" || message.type === "test_message") {
          if (onMessage) {
            console.log("📨 Priority SSE message:", message.type);
            onMessage(message);
          }
          return;
        }

        // status_update messages are debounced (but important states are handled immediately)
        if (message.type === "status_update") {
          console.log("📨 Status update received:", message.data.id, "진행률:" + message.data.progress + "%", "상태:" + message.data.status);
          
          // Important state changes are handled immediately (stopped, done, failed, downloading)
          if (message.data.status === "stopped" || 
              message.data.status === "done" || 
              message.data.status === "failed" ||
              (message.data.status === "downloading" && message.data.progress > 0)) {
            console.log("📨 즉시 처리:", message.data.id, message.data.status);
            if (onMessage) {
              onMessage(message);
            }
            return;
          }
          
          this.queueUpdate(message, onMessage);
          return;
        }

        // All other messages are handled immediately
        if (onMessage) {
          console.log("📨 SSE message received:", message.type);
          onMessage(message);
        }
      } catch (error) {
        console.warn("SSE message parse error:", error);
      }
    };

    this.eventSource.onerror = (error) => {
      console.log("⚠️ EventSource error, attempting reconnect. State:", this.eventSource.readyState);
      this.reconnectAttempts = (this.reconnectAttempts || 0) + 1;
      
      // Allow more retries in a Cloudflare environment
      if (this.reconnectAttempts > 15) {
        console.log("❌ EventSource max reconnect attempts reached");
        return;
      }
      
      // On a Cloudflare tunnel, reconnect with a shorter delay (fast recovery)
      const delay = Math.min(1000 + (this.reconnectAttempts * 500), 8000);
      console.log(`🔄 Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/15)`);
      setTimeout(() => {
        this.reconnect();
      }, delay);
    };
  }

  reconnect() {
    // Close any existing connection
    if (this.eventSource) {
      this.eventSource.close();
    }

    // Reconnect after a short delay (avoids server load)
    setTimeout(() => {
      this.connect(this.lastOnMessage);
    }, 1000);
  }

  queueUpdate(message, onMessage) {
    const downloadId = message.data.id;
    
    // For updates with the same download ID, keep only the latest one
    this.updateQueue.set(downloadId, { message, onMessage });

    // Cancel the existing timer
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }

    // Set a new timer
    this.debounceTimer = setTimeout(() => {
      this.flushUpdates();
    }, this.debounceDelay);
  }

  flushUpdates() {
    if (this.updateQueue.size === 0) return;
    
    console.log(`📦 Flushing ${this.updateQueue.size} queued updates`);
    
    // Process all queued updates in a batch
    const updates = Array.from(this.updateQueue.values());
    this.updateQueue.clear();

    // Process the merged updates all at once
    if (updates.length > 0) {
      const batchMessage = {
        type: "batch_status_update",
        data: updates.map(u => u.message.data)
      };
      
      updates[0].onMessage(batchMessage);
    }
  }

  isConnected() {
    return this.eventSource && this.eventSource.readyState === EventSource.OPEN;
  }

  disconnect() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    
    // Clean up the timer and queue
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
    this.updateQueue.clear();
  }
}