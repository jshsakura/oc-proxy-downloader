  // 조용한 백그라운드 동기화 (깜빡거림 없음)
  async function syncDownloadsSilently() {
    try {
      const response = await fetch(`/api/history/`);
      if (response.ok) {
        const data = await response.json();
        // 기존 항목들과 병합하여 깜빡거림 방지
        downloads = data;
      }
    } catch (error) {
      console.error("Background sync failed:", error);
    }
  }