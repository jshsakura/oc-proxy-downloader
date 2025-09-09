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

    this.eventSource = new EventSource("/api/events");

    this.eventSource.onopen = () => {
      console.log("EventSource connected");
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
      // EventSource는 자동으로 재연결을 시도함
      console.log("EventSource error, will auto-reconnect");
    };
  }

  disconnect() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  reconnect(onMessage) {
    this.connect(onMessage);
  }

  isConnected() {
    return this.eventSource && this.eventSource.readyState === EventSource.OPEN;
  }
}