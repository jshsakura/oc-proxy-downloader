import { writable } from 'svelte/store';

export const toastMessage = writable('');
export const toastType = writable('info'); // 'success', 'error', 'warning', 'info'
export const showToast = writable(false);

let toastTimer;
let lastToastMessage = '';
let lastToastTime = 0;
const DUPLICATE_THRESHOLD = 1000; // 1초 내 같은 메시지 중복 방지

export function showToastMsg(msg, type = 'info') {
  if (typeof msg !== 'string') {
    if (msg && typeof msg.message === 'string') {
      msg = msg.message;
    } else {
      return;
    }
  }
  
  // 중복 메시지 방지 (1초 내 같은 메시지)
  const now = Date.now();
  if (msg === lastToastMessage && (now - lastToastTime) < DUPLICATE_THRESHOLD) {
    return;
  }
  
  lastToastMessage = msg;
  lastToastTime = now;
  
  toastMessage.set(msg);
  toastType.set(type);
  showToast.set(true);
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    showToast.set(false);
  }, 2500);
} 