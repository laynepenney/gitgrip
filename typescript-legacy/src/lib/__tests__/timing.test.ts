import { describe, it, expect } from 'vitest';
import {
  Timer,
  TimingContext,
  formatDuration,
  formatTimingReport,
  calculateStats,
  runBenchmark,
  formatBenchmarkResults,
} from '../timing.js';

describe('Timer', () => {
  it('measures elapsed time', async () => {
    const timer = new Timer().start();
    await new Promise((resolve) => setTimeout(resolve, 10));
    timer.stop();

    const elapsed = timer.elapsed();
    expect(elapsed).toBeGreaterThan(5);
    expect(elapsed).toBeLessThan(100);
  });

  it('throws if stopped without starting', () => {
    const timer = new Timer();
    expect(() => timer.stop()).toThrow('Timer was not started');
  });

  it('returns 0 if elapsed called without starting', () => {
    const timer = new Timer();
    expect(timer.elapsed()).toBe(0);
  });

  it('reports running state correctly', () => {
    const timer = new Timer();
    expect(timer.isRunning()).toBe(false);

    timer.start();
    expect(timer.isRunning()).toBe(true);

    timer.stop();
    expect(timer.isRunning()).toBe(false);
  });

  it('can get elapsed while running', async () => {
    const timer = new Timer().start();
    await new Promise((resolve) => setTimeout(resolve, 5));

    const elapsed1 = timer.elapsed();
    expect(elapsed1).toBeGreaterThan(0);

    await new Promise((resolve) => setTimeout(resolve, 5));
    const elapsed2 = timer.elapsed();
    expect(elapsed2).toBeGreaterThan(elapsed1);
  });
});

describe('TimingContext', () => {
  it('tracks simple phases', async () => {
    const ctx = new TimingContext(true);

    await ctx.time('phase1', async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
    });

    const report = ctx.getReport();
    expect(report.entries).toHaveLength(1);
    expect(report.entries[0].label).toBe('phase1');
    expect(report.entries[0].duration).toBeGreaterThan(0);
  });

  it('tracks nested phases', async () => {
    const ctx = new TimingContext(true);

    await ctx.time('outer', async () => {
      await ctx.time('inner1', async () => {
        await new Promise((resolve) => setTimeout(resolve, 2));
      });
      await ctx.time('inner2', async () => {
        await new Promise((resolve) => setTimeout(resolve, 2));
      });
    });

    const report = ctx.getReport();
    expect(report.entries).toHaveLength(1);
    expect(report.entries[0].label).toBe('outer');
    expect(report.entries[0].children).toHaveLength(2);
    expect(report.entries[0].children![0].label).toBe('inner1');
    expect(report.entries[0].children![1].label).toBe('inner2');
  });

  it('tracks multiple root phases', async () => {
    const ctx = new TimingContext(true);

    await ctx.time('phase1', async () => {});
    await ctx.time('phase2', async () => {});

    const report = ctx.getReport();
    expect(report.entries).toHaveLength(2);
    expect(report.entries[0].label).toBe('phase1');
    expect(report.entries[1].label).toBe('phase2');
  });

  it('supports manual start/end phase', () => {
    const ctx = new TimingContext(true);

    ctx.startPhase('manual');
    ctx.endPhase('manual');

    const report = ctx.getReport();
    expect(report.entries).toHaveLength(1);
    expect(report.entries[0].label).toBe('manual');
  });

  it('throws on phase mismatch', () => {
    const ctx = new TimingContext(true);

    ctx.startPhase('phase1');
    expect(() => ctx.endPhase('phase2')).toThrow('Phase mismatch');
  });

  it('throws when ending without active phase', () => {
    const ctx = new TimingContext(true);

    expect(() => ctx.endPhase('nonexistent')).toThrow('No active phase');
  });

  it('returns empty report when disabled', async () => {
    const ctx = new TimingContext(false);

    await ctx.time('phase1', async () => {
      await new Promise((resolve) => setTimeout(resolve, 5));
    });

    const report = ctx.getReport();
    expect(report.total).toBe(0);
    expect(report.entries).toHaveLength(0);
  });

  it('executes function even when disabled', async () => {
    const ctx = new TimingContext(false);
    let executed = false;

    await ctx.time('phase1', async () => {
      executed = true;
    });

    expect(executed).toBe(true);
  });

  it('tracks total time', async () => {
    const ctx = new TimingContext(true);

    await new Promise((resolve) => setTimeout(resolve, 10));

    const report = ctx.getReport();
    expect(report.total).toBeGreaterThan(5);
  });

  it('supports sync timing', () => {
    const ctx = new TimingContext(true);

    const result = ctx.timeSync('sync-op', () => {
      let sum = 0;
      for (let i = 0; i < 1000; i++) sum += i;
      return sum;
    });

    expect(result).toBe(499500);
    const report = ctx.getReport();
    expect(report.entries).toHaveLength(1);
    expect(report.entries[0].label).toBe('sync-op');
  });
});

describe('formatDuration', () => {
  it('formats microseconds', () => {
    expect(formatDuration(0.5)).toBe('500µs');
    expect(formatDuration(0.001)).toBe('1µs');
  });

  it('formats milliseconds', () => {
    expect(formatDuration(1)).toBe('1ms');
    expect(formatDuration(100)).toBe('100ms');
    expect(formatDuration(999)).toBe('999ms');
  });

  it('formats seconds', () => {
    expect(formatDuration(1000)).toBe('1.00s');
    expect(formatDuration(1500)).toBe('1.50s');
    expect(formatDuration(59999)).toBe('60.00s');
  });

  it('formats minutes', () => {
    expect(formatDuration(60000)).toBe('1m 0.0s');
    expect(formatDuration(90000)).toBe('1m 30.0s');
    expect(formatDuration(125000)).toBe('2m 5.0s');
  });
});

describe('formatTimingReport', () => {
  it('formats a simple report', () => {
    const report = {
      total: 1234,
      entries: [
        { label: 'phase1', duration: 500 },
        { label: 'phase2', duration: 734 },
      ],
    };

    const output = formatTimingReport(report);
    expect(output).toContain('Timing Report');
    expect(output).toContain('Total: 1.23s');
    expect(output).toContain('phase1');
    expect(output).toContain('phase2');
  });

  it('formats nested entries', () => {
    const report = {
      total: 1000,
      entries: [
        {
          label: 'outer',
          duration: 1000,
          children: [
            { label: 'inner1', duration: 400 },
            { label: 'inner2', duration: 600 },
          ],
        },
      ],
    };

    const output = formatTimingReport(report);
    expect(output).toContain('outer');
    expect(output).toContain('inner1');
    expect(output).toContain('inner2');
    expect(output).toContain('├─');
    expect(output).toContain('└─');
  });
});

describe('calculateStats', () => {
  it('calculates stats for a set of values', () => {
    const values = [10, 20, 30, 40, 50];
    const stats = calculateStats(values);

    expect(stats.min).toBe(10);
    expect(stats.max).toBe(50);
    expect(stats.avg).toBe(30);
    expect(stats.p50).toBe(30);
  });

  it('returns zeros for empty array', () => {
    const stats = calculateStats([]);

    expect(stats.min).toBe(0);
    expect(stats.max).toBe(0);
    expect(stats.avg).toBe(0);
    expect(stats.stdDev).toBe(0);
  });

  it('calculates standard deviation', () => {
    const values = [2, 4, 4, 4, 5, 5, 7, 9];
    const stats = calculateStats(values);

    // Mean = 5, variance = 4, stdDev = 2
    expect(stats.avg).toBe(5);
    expect(stats.stdDev).toBeCloseTo(2, 1);
  });
});

describe('runBenchmark', () => {
  it('runs benchmark with specified iterations', async () => {
    let count = 0;
    const result = await runBenchmark(
      'test-bench',
      async () => {
        count++;
      },
      { iterations: 3, warmup: 1 }
    );

    expect(result.name).toBe('test-bench');
    expect(result.iterations).toBe(3);
    expect(count).toBe(4); // 1 warmup + 3 iterations
    expect(result.min).toBeGreaterThanOrEqual(0);
    expect(result.max).toBeGreaterThanOrEqual(result.min);
  });

  it('uses default iterations and warmup', async () => {
    let count = 0;
    const result = await runBenchmark('test-bench', async () => {
      count++;
    });

    expect(result.iterations).toBe(5);
    expect(count).toBe(6); // 1 warmup + 5 iterations
  });
});

describe('formatBenchmarkResults', () => {
  it('formats results as a table', () => {
    const results = [
      { name: 'operation1', iterations: 5, min: 10, max: 20, avg: 15, p50: 15, p95: 19, stdDev: 3 },
      { name: 'operation2', iterations: 5, min: 100, max: 200, avg: 150, p50: 150, p95: 190, stdDev: 30 },
    ];

    const output = formatBenchmarkResults(results);
    expect(output).toContain('Workspace Benchmark Results');
    expect(output).toContain('Operation');
    expect(output).toContain('operation1');
    expect(output).toContain('operation2');
    expect(output).toContain('│');
  });
});
