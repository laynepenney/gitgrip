import { describe, bench } from 'vitest';

/**
 * Performance benchmarks for parallelized operations.
 * These test the parallel execution patterns used in push/sync/commit.
 *
 * Run with: pnpm bench
 *
 * For full workspace benchmarks, use: gr bench
 */

describe('Parallel execution patterns', () => {
  // Simulate async operations like git status checks
  const simulateGitOperation = (delayMs: number) =>
    new Promise<number>(resolve => setTimeout(() => resolve(delayMs), delayMs));

  const repos = Array.from({ length: 5 }, (_, i) => ({ name: `repo-${i}`, delay: 10 + i * 5 }));

  bench('sequential execution (baseline)', async () => {
    const results: number[] = [];
    for (const repo of repos) {
      const result = await simulateGitOperation(repo.delay);
      results.push(result);
    }
  });

  bench('parallel execution with Promise.all', async () => {
    await Promise.all(
      repos.map(repo => simulateGitOperation(repo.delay))
    );
  });

  bench('two-phase parallel (gather then process)', async () => {
    // Phase 1: Gather info in parallel
    const infos = await Promise.all(
      repos.map(async repo => ({
        repo,
        needsProcess: repo.delay > 15, // Simulate filtering
      }))
    );

    // Phase 2: Process filtered items in parallel
    const toProcess = infos.filter(i => i.needsProcess);
    await Promise.all(
      toProcess.map(({ repo }) => simulateGitOperation(repo.delay))
    );
  });
});

describe('GitStatusCache simulation', () => {
  const cache = new Map<string, { value: number; timestamp: number }>();
  const TTL = 5000;

  const getCachedValue = async (key: string): Promise<number> => {
    const cached = cache.get(key);
    if (cached && Date.now() - cached.timestamp < TTL) {
      return cached.value;
    }
    // Simulate expensive operation
    const value = Math.random();
    cache.set(key, { value, timestamp: Date.now() });
    return value;
  };

  bench('uncached lookups', async () => {
    cache.clear();
    for (let i = 0; i < 10; i++) {
      await getCachedValue(`key-${i % 3}`);
    }
  });

  bench('cached lookups (warm cache)', async () => {
    // Pre-warm cache
    for (let i = 0; i < 3; i++) {
      await getCachedValue(`key-${i}`);
    }
    // Now all lookups should be cached
    for (let i = 0; i < 10; i++) {
      await getCachedValue(`key-${i % 3}`);
    }
  });
});
