import { describe, it, expect, vi } from 'vitest';
import { withRetry, isRetryableError, createRetryWrapper } from '../retry.js';

describe('retry utilities', () => {
  describe('isRetryableError', () => {
    it('returns true for network errors', () => {
      expect(isRetryableError(new Error('ECONNRESET'))).toBe(true);
      expect(isRetryableError(new Error('ETIMEDOUT'))).toBe(true);
      expect(isRetryableError(new Error('socket hang up'))).toBe(true);
      expect(isRetryableError(new Error('network error'))).toBe(true);
    });

    it('returns true for 5xx errors', () => {
      expect(isRetryableError(new Error('500 Internal Server Error'))).toBe(true);
      expect(isRetryableError(new Error('503 Service Unavailable'))).toBe(true);
      expect(isRetryableError({ status: 502 })).toBe(true);
      expect(isRetryableError({ statusCode: 504 })).toBe(true);
    });

    it('returns true for rate limit errors (429)', () => {
      expect(isRetryableError(new Error('429 Too Many Requests'))).toBe(true);
      expect(isRetryableError({ status: 429 })).toBe(true);
    });

    it('returns false for client errors', () => {
      expect(isRetryableError(new Error('404 Not Found'))).toBe(false);
      expect(isRetryableError(new Error('400 Bad Request'))).toBe(false);
      expect(isRetryableError({ status: 401 })).toBe(false);
    });

    it('returns false for non-errors', () => {
      expect(isRetryableError(null)).toBe(false);
      expect(isRetryableError(undefined)).toBe(false);
    });
  });

  describe('withRetry', () => {
    it('returns result on first success', async () => {
      const fn = vi.fn().mockResolvedValue('success');

      const result = await withRetry(fn);

      expect(result).toBe('success');
      expect(fn).toHaveBeenCalledTimes(1);
    });

    it('retries on retryable errors', async () => {
      const fn = vi
        .fn()
        .mockRejectedValueOnce(new Error('ECONNRESET'))
        .mockRejectedValueOnce(new Error('503'))
        .mockResolvedValue('success');

      // Use very small delays for testing
      const result = await withRetry(fn, { maxRetries: 3, initialDelay: 1 });

      expect(result).toBe('success');
      expect(fn).toHaveBeenCalledTimes(3);
    });

    it('throws after max retries exhausted', async () => {
      const error = new Error('500 Server Error');
      const fn = vi.fn().mockRejectedValue(error);

      await expect(
        withRetry(fn, { maxRetries: 2, initialDelay: 1 })
      ).rejects.toThrow('500 Server Error');
      expect(fn).toHaveBeenCalledTimes(3); // Initial + 2 retries
    });

    it('does not retry on non-retryable errors', async () => {
      const error = new Error('404 Not Found');
      const fn = vi.fn().mockRejectedValue(error);

      await expect(withRetry(fn, { maxRetries: 3, initialDelay: 1 })).rejects.toThrow('404 Not Found');
      expect(fn).toHaveBeenCalledTimes(1);
    });

    it('calls onRetry callback', async () => {
      const fn = vi
        .fn()
        .mockRejectedValueOnce(new Error('500'))
        .mockResolvedValue('success');

      const onRetry = vi.fn();

      const result = await withRetry(fn, {
        maxRetries: 3,
        initialDelay: 1,
        onRetry,
      });

      expect(result).toBe('success');
      expect(onRetry).toHaveBeenCalledTimes(1);
      expect(onRetry).toHaveBeenCalledWith(1, expect.any(Error), expect.any(Number));
    });

    it('respects maxDelay', async () => {
      const fn = vi.fn().mockRejectedValue(new Error('500'));
      const onRetry = vi.fn();

      await expect(
        withRetry(fn, {
          maxRetries: 3,
          initialDelay: 10,
          maxDelay: 20,
          jitter: 0,
          onRetry,
        })
      ).rejects.toThrow();

      // Check that delay never exceeds maxDelay
      for (const call of onRetry.mock.calls) {
        expect(call[2]).toBeLessThanOrEqual(20);
      }
    });

    it('uses custom isRetryable function', async () => {
      const fn = vi
        .fn()
        .mockRejectedValueOnce(new Error('CUSTOM_ERROR'))
        .mockResolvedValue('success');

      const isRetryable = (err: unknown) => {
        return err instanceof Error && err.message === 'CUSTOM_ERROR';
      };

      const result = await withRetry(fn, {
        maxRetries: 3,
        initialDelay: 1,
        isRetryable,
      });

      expect(result).toBe('success');
      expect(fn).toHaveBeenCalledTimes(2);
    });
  });

  describe('createRetryWrapper', () => {
    it('creates a wrapper with default options', async () => {
      const retryable = createRetryWrapper({ maxRetries: 1, initialDelay: 1 });

      const fn = vi.fn().mockResolvedValue('success');
      const result = await retryable(fn);

      expect(result).toBe('success');
    });

    it('allows overriding options per call', async () => {
      const retryable = createRetryWrapper({ maxRetries: 1, initialDelay: 1 });

      const fn = vi.fn().mockRejectedValue(new Error('500'));

      await expect(retryable(fn, { maxRetries: 0 })).rejects.toThrow();
      expect(fn).toHaveBeenCalledTimes(1);
    });
  });
});
