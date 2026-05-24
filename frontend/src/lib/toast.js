import { writable } from 'svelte/store';

export const toastMessage = writable('');
export const toastType = writable('info'); // 'success', 'error', 'warning', 'info'
export const showToast = writable(false);

let toastTimer;
let lastToastMessage = '';
let lastToastTime = 0;
const DUPLICATE_THRESHOLD = 1000; // Prevent duplicate messages within 1 second

export function showToastMsg(msg, type = 'info') {
  if (typeof msg !== 'string') {
    if (msg && typeof msg.message === 'string') {
      msg = msg.message;
    } else {
      return;
    }
  }
  
  // Prevent duplicate messages (same message within 1 second)
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