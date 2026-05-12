/**
 * Utility functions for the frontend
 */

export function formatBytes(bytes, decimals = 2) {
    if (!bytes || bytes === 0) return "0 Bytes";
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    const val = bytes / Math.pow(k, i);
    return val.toFixed(dm).replace(/\.00$/, "") + " " + sizes[i];
}

export function formatWaitTime(seconds) {
    if (seconds == null || seconds < 0) return "0:00";
    const total = Math.max(0, Math.floor(seconds));
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatSpeed(bytesPerSecond) {
    if (!bytesPerSecond || bytesPerSecond === 0) return "0 B/s";
    const k = 1024;
    const sizes = ["B/s", "KB/s", "MB/s", "GB/s"];
    const i = Math.floor(Math.log(bytesPerSecond) / Math.log(k));
    const speed = (bytesPerSecond / Math.pow(k, i)).toFixed(i >= 2 ? 2 : 1);
    return speed + " " + sizes[i];
}

export function formatDate(dateString, locale = 'en') {
    if (!dateString) return "-";
    const date = new Date(dateString);
    const today = new Date();

    // 오늘이면 시간만 표시
    if (date.toDateString() === today.toDateString()) {
      return date.toLocaleTimeString(
        locale === "ko" ? "ko-KR" : "en-US",
        {
          hour: "2-digit",
          minute: "2-digit",
        }
      );
    }

    // 어제 이전이면 간단한 날짜 형식
    if (locale === "ko") {
      return `${date.getMonth() + 1}월 ${date.getDate()}일`;
    } else {
      return date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      });
    }
}

export function formatTime(dateString) {
    if (!dateString) return "-";
    const date = new Date(dateString);
    return (
      String(date.getHours()).padStart(2, "0") +
      ":" +
      String(date.getMinutes()).padStart(2, "0") +
      ":" +
      String(date.getSeconds()).padStart(2, "0")
    );
}

export function getDownloadProgress(download) {
    if (download.progress !== undefined && download.progress !== null) {
      return Math.round(download.progress * 2) / 2; // 0.5% 단위로 반올림
    }

    const downloaded = Number(
      download.downloaded_size ?? download.downloaded ?? 0
    );
    const total = Number(download.total_size ?? download.file_size ?? 0);
    if (total === 0 || download.status === "pending") return 0;
    if (download.status === "done") return 100;
    return Math.round((downloaded / total) * 100);
}

export function isValidUrl(string) {
    try {
      const url = new URL(string);
      return url.protocol === "http:" || url.protocol === "https:";
    } catch (_) {
      return false;
    }
}

export function isMobileDevice() {
    if (typeof navigator === 'undefined') return false;
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
}
