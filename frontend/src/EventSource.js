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
        
        // heartbeat 메시지는 무시
        if (message.type === "heartbeat") {
          return;
        }

        if (onMessage) {
          onMessage(message);
        }
      } catch (error) {
        // JSON 파싱 에러 무시
      }
    };

    this.eventSource.onerror = (error) => {
      console.log("EventSource error, attempting reconnect");
      this.reconnectAttempts = (this.reconnectAttempts || 0) + 1;
      
      // 너무 많은 재시도는 방지 (최대 5회)
      if (this.reconnectAttempts > 5) {
        console.log("EventSource max reconnect attempts reached");
        return;
      }
      
      // 지수 백오프로 재연결 지연
      const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
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