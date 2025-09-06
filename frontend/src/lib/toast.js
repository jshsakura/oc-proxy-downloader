import { writable } from 'svelte/store';

export const toastMessage = writable('');
export const toastType = writable('info'); // 'success', 'error', 'warning', 'info'
export const showToast = writable(false);

let toastTimer;
export function showToastMsg(msg, type = 'info') {
  if (typeof msg !== 'string') {
    if (msg && typeof msg.message === 'string') {
      msg = msg.message;
    } else {
      return;
    }
  }
  toastMessage.set(msg);
  toastType.set(type);
  showToast.set(true);
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => showToast.set(false), 3000); // 시간을 3초로 늘림
} 