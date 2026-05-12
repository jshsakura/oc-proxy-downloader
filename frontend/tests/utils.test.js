import { describe, it, expect } from 'vitest';
import { formatBytes, formatWaitTime, isValidUrl } from '../src/lib/utils';

describe('Frontend Utils', () => {
  it('formatBytes should format correctly', () => {
    expect(formatBytes(0)).toBe('0 Bytes');
    expect(formatBytes(1024)).toBe('1.00 KB');
    expect(formatBytes(1024 * 1024)).toBe('1.00 MB');
  });

  it('formatWaitTime should format correctly', () => {
    expect(formatWaitTime(65)).toBe('1:05');
    expect(formatWaitTime(10)).toBe('0:10');
    expect(formatWaitTime(0)).toBe('0:00');
    expect(formatWaitTime(null)).toBe('0:00');
  });

  it('isValidUrl should validate correctly', () => {
    expect(isValidUrl('https://google.com')).toBe(true);
    expect(isValidUrl('http://localhost:3000')).toBe(true);
    expect(isValidUrl('not-a-url')).toBe(false);
  });
});
