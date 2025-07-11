import { writable } from 'svelte/store';

export const toastMessage = writable('');
export const showToast = writable(false);

let toastTimer;
export function showToastMsg(msg) {
  if (typeof msg !== 'string') {
    if (msg && typeof msg.message === 'string') {
      msg = msg.message;
    } else {
      // 객체면 토스트 띄우지 않음
      return;
    }
  }
  toastMessage.set(msg);
  showToast.set(true);
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => showToast.set(false), 2000);
} 