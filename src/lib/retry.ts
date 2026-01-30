/**
 * Retry utility with exponential backoff for transient API failures
 */

export interface RetryOptions {
  /** Maximum number of retry attempts (default: 3) */
  maxRetries?: number;
  /** Initial delay in milliseconds (default: 1000) */
  initialDelay?: number;
  /** Maximum delay in milliseconds (default: 30000) */
  maxDelay?: number;
  /** Jitter factor (0-1) to randomize delay (default: 0.1) */
  jitter?: number;
  /** Custom function to determine if error is retryable */
  isRetryable?: (error: unknown) => boolean;
  /** Callback for each retry attempt */
  onRetry?: (attempt: number, error: unknown, delay: number) => void;
}

/**
 * Default check for retryable errors
 * Retries on: network errors, 5xx errors, 429 (rate limit)
 * Does NOT retry on: 4xx client errors (except 429)
 */
export function isRetryableError(error: unknown): boolean {
  if (!error) return false;

  // Network errors
  const errorMessage = error instanceof Error ? error.message.toLowerCase() : String(error).toLowerCase();
  const networkErrors = [
    'econnreset',
    'econnrefused',
    'etimedout',
    'enotfound',
    'socket hang up',
    'network error',
    'fetch failed',
  ];
  if (networkErrors.some((e) => errorMessage.includes(e))) {
    return true;
  }

  // Check for status property on error object first (more reliable)
  if (typeof error === 'object' && error !== null) {
    const errorObj = error as { status?: number; statusCode?: number };
    const status = errorObj.status ?? errorObj.statusCode;
    if (status !== undefined) {
      // Retry only on 5xx (server errors) and 429 (rate limit)
      return status >= 500 || status === 429;
    }
  }

  // HTTP status code from error message (less reliable, be strict)
  // Match patterns like "404", "500", "503 Service Unavailable"
  const statusMatch = errorMessage.match(/\b([45]\d{2})\b/);
  if (statusMatch) {
    const status = parseInt(statusMatch[1], 10);
    // Retry on 5xx (server errors) and 429 (rate limit)
    // Do NOT retry on other 4xx errors
    return status >= 500 || status === 429;
  }

  return false;
}

/**
 * Sleep for a specified duration
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Calculate delay with exponential backoff and jitter
 */
function calculateDelay(
  attempt: number,
  initialDelay: number,
  maxDelay: number,
  jitter: number
): number {
  // Exponential backoff: initialDelay * 2^attempt
  const exponentialDelay = initialDelay * Math.pow(2, attempt);
  const clampedDelay = Math.min(exponentialDelay, maxDelay);

  // Add jitter to prevent thundering herd
  const jitterAmount = clampedDelay * jitter * (Math.random() * 2 - 1);
  return Math.max(0, Math.round(clampedDelay + jitterAmount));
}

/**
 * Execute a function with retry logic and exponential backoff
 *
 * @example
 * ```typescript
 * const result = await withRetry(
 *   () => fetchPullRequest(owner, repo, number),
 *   { maxRetries: 3, initialDelay: 1000 }
 * );
 * ```
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  options: RetryOptions = {}
): Promise<T> {
  const {
    maxRetries = 3,
    initialDelay = 1000,
    maxDelay = 30000,
    jitter = 0.1,
    isRetryable = isRetryableError,
    onRetry,
  } = options;

  let lastError: unknown;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;

      // Check if we should retry
      const canRetry = attempt < maxRetries;
      const shouldRetry = canRetry && isRetryable(error);

      if (!shouldRetry) {
        // Either non-retryable error or exhausted retries
        throw error;
      }

      const delay = calculateDelay(attempt, initialDelay, maxDelay, jitter);

      if (onRetry) {
        onRetry(attempt + 1, error, delay);
      }

      await sleep(delay);
    }
  }

  // All retries exhausted (this should not be reached due to throw above)
  throw lastError;
}

/**
 * Create a retry wrapper with pre-configured options
 *
 * @example
 * ```typescript
 * const retryableApiCall = createRetryWrapper({ maxRetries: 5 });
 * const result = await retryableApiCall(() => api.getData());
 * ```
 */
export function createRetryWrapper(defaultOptions: RetryOptions = {}) {
  return function <T>(fn: () => Promise<T>, options?: RetryOptions): Promise<T> {
    return withRetry(fn, { ...defaultOptions, ...options });
  };
}
