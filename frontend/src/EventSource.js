// EventSource 관리 모듈
export class EventSourceManager {
  constructor() {
    this.eventSource = null;
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

        // 실제 데이터 메시지 처리
        if (onMessage) {
          console.log("📨 SSE message received:", message.type, message);
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

  disconnect() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
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

  isConnected() {
    return this.eventSource && this.eventSource.readyState === EventSource.OPEN;
  }
}