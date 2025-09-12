// EventSource 관리 모듈
export class EventSourceManager {
  constructor() {
    this.eventSource = null;
    this.updateQueue = new Map();
    this.debounceTimer = null;
    this.debounceDelay = 50; // 50ms 디바운싱으로 더 빠르게
  }

  connect(onMessage) {
    // 기존 연결이 있으면 닫기
    if (this.eventSource) {
      this.eventSource.close();
    }

    // 마지막 onMessage 콜백 저장 (재연결용)
    this.lastOnMessage = onMessage;

    this.eventSource = new EventSource("/api/events");

    this.eventSource.onopen = () => {
      console.log("EventSource connected");
      this.reconnectAttempts = 0; // 연결 성공 시 재시도 횟수 초기화
    };

    this.eventSource.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        
        // heartbeat과 connection 메시지는 연결 상태 확인용으로만 사용
        if (message.type === "heartbeat") {
          console.log("💓 SSE heartbeat received", message.queue_size ? `(queue: ${message.queue_size})` : "");
          return;
        }
        
        if (message.type === "connection") {
          console.log("🔌 SSE connection established:", message.status);
          return;
        }

        // 중요한 메시지는 즉시 처리
        if (message.type === "force_refresh" || message.type === "test_message") {
          if (onMessage) {
            console.log("📨 Priority SSE message:", message.type);
            onMessage(message);
          }
          return;
        }

        // status_update 메시지는 디바운싱 처리 (하지만 중요한 상태는 즉시 처리)
        if (message.type === "status_update") {
          console.log("📨 Status update received:", message.data.id, "진행률:" + message.data.progress + "%", "상태:" + message.data.status);
          
          // 중요한 상태 변경은 즉시 처리 (정지, 완료, 실패, 다운로드 중)
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

        // 나머지 메시지는 즉시 처리
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
      
      // 클라우드플레어 환경에서는 더 많은 재시도 허용
      if (this.reconnectAttempts > 15) {
        console.log("❌ EventSource max reconnect attempts reached");
        return;
      }
      
      // 클라우드플레어 터널에서는 더 짧은 지연으로 재연결 (빠른 복구)
      const delay = Math.min(1000 + (this.reconnectAttempts * 500), 8000);
      console.log(`🔄 Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/15)`);
      setTimeout(() => {
        this.reconnect();
      }, delay);
    };
  }

  reconnect() {
    // 기존 연결이 있으면 닫기
    if (this.eventSource) {
      this.eventSource.close();
    }
    
    // 짧은 지연 후 재연결 (서버 부하 방지)
    setTimeout(() => {
      this.connect(this.lastOnMessage);
    }, 1000);
  }

  queueUpdate(message, onMessage) {
    const downloadId = message.data.id;
    
    // 같은 다운로드 ID의 업데이트는 마지막 것만 유지
    this.updateQueue.set(downloadId, { message, onMessage });
    
    // 기존 타이머 취소
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }
    
    // 새 타이머 설정
    this.debounceTimer = setTimeout(() => {
      this.flushUpdates();
    }, this.debounceDelay);
  }

  flushUpdates() {
    if (this.updateQueue.size === 0) return;
    
    console.log(`📦 Flushing ${this.updateQueue.size} queued updates`);
    
    // 큐에 있는 모든 업데이트를 일괄 처리
    const updates = Array.from(this.updateQueue.values());
    this.updateQueue.clear();
    
    // 합쳐진 업데이트로 한 번에 처리
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
    
    // 타이머와 큐 정리
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
    this.updateQueue.clear();
  }
}