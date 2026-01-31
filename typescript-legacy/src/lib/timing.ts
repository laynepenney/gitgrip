import type { TimingEntry, TimingReport, BenchmarkResult } from '../types.js';

/**
 * High-resolution timer using process.hrtime.bigint()
 */
export class Timer {
  private startTime: bigint | null = null;
  private endTime: bigint | null = null;

  /**
   * Start the timer
   */
  start(): this {
    this.startTime = process.hrtime.bigint();
    this.endTime = null;
    return this;
  }

  /**
   * Stop the timer
   */
  stop(): this {
    if (this.startTime === null) {
      throw new Error('Timer was not started');
    }
    this.endTime = process.hrtime.bigint();
    return this;
  }

  /**
   * Get elapsed time in milliseconds
   */
  elapsed(): number {
    if (this.startTime === null) {
      return 0;
    }
    const end = this.endTime ?? process.hrtime.bigint();
    return Number(end - this.startTime) / 1_000_000;
  }

  /**
   * Check if the timer is running
   */
  isRunning(): boolean {
    return this.startTime !== null && this.endTime === null;
  }
}

/**
 * Internal tracking for a timing phase
 */
interface PhaseTracker {
  label: string;
  timer: Timer;
  children: PhaseTracker[];
  parent: PhaseTracker | null;
}

/**
 * Hierarchical timing context for tracking nested operations
 */
export class TimingContext {
  private enabled: boolean;
  private rootPhases: PhaseTracker[] = [];
  private currentPhase: PhaseTracker | null = null;
  private overallTimer: Timer;

  constructor(enabled = true) {
    this.enabled = enabled;
    this.overallTimer = new Timer();
    if (enabled) {
      this.overallTimer.start();
    }
  }

  /**
   * Time an async operation
   */
  async time<T>(label: string, fn: () => Promise<T>): Promise<T> {
    if (!this.enabled) {
      return fn();
    }

    this.startPhase(label);
    try {
      return await fn();
    } finally {
      this.endPhase(label);
    }
  }

  /**
   * Time a sync operation
   */
  timeSync<T>(label: string, fn: () => T): T {
    if (!this.enabled) {
      return fn();
    }

    this.startPhase(label);
    try {
      return fn();
    } finally {
      this.endPhase(label);
    }
  }

  /**
   * Start a new timing phase
   */
  startPhase(label: string): void {
    if (!this.enabled) return;

    const phase: PhaseTracker = {
      label,
      timer: new Timer().start(),
      children: [],
      parent: this.currentPhase,
    };

    if (this.currentPhase) {
      this.currentPhase.children.push(phase);
    } else {
      this.rootPhases.push(phase);
    }

    this.currentPhase = phase;
  }

  /**
   * End a timing phase
   */
  endPhase(label: string): void {
    if (!this.enabled) return;

    if (!this.currentPhase) {
      throw new Error(`No active phase to end (expected: ${label})`);
    }

    if (this.currentPhase.label !== label) {
      throw new Error(`Phase mismatch: expected "${this.currentPhase.label}", got "${label}"`);
    }

    this.currentPhase.timer.stop();
    this.currentPhase = this.currentPhase.parent;
  }

  /**
   * Check if timing is enabled
   */
  isEnabled(): boolean {
    return this.enabled;
  }

  /**
   * Convert phase tracker to timing entry
   */
  private phaseToEntry(phase: PhaseTracker): TimingEntry {
    const entry: TimingEntry = {
      label: phase.label,
      duration: phase.timer.elapsed(),
    };

    if (phase.children.length > 0) {
      entry.children = phase.children.map((child) => this.phaseToEntry(child));
    }

    return entry;
  }

  /**
   * Get the timing report
   */
  getReport(): TimingReport {
    if (!this.enabled) {
      return { total: 0, entries: [] };
    }

    return {
      total: this.overallTimer.elapsed(),
      entries: this.rootPhases.map((phase) => this.phaseToEntry(phase)),
    };
  }
}

/**
 * Format a duration in milliseconds to a human-readable string
 */
export function formatDuration(ms: number): string {
  if (ms < 1) {
    return `${(ms * 1000).toFixed(0)}µs`;
  }
  if (ms < 1000) {
    return `${ms.toFixed(0)}ms`;
  }
  if (ms < 60000) {
    return `${(ms / 1000).toFixed(2)}s`;
  }
  const minutes = Math.floor(ms / 60000);
  const seconds = (ms % 60000) / 1000;
  return `${minutes}m ${seconds.toFixed(1)}s`;
}

/**
 * Format a timing entry with tree structure
 */
function formatEntry(entry: TimingEntry, indent = 0, isLast = true, prefix = ''): string[] {
  const lines: string[] = [];
  const duration = formatDuration(entry.duration).padStart(8);

  if (indent === 0) {
    lines.push(`  ${entry.label.padEnd(24)} ${duration}`);
  } else {
    const connector = isLast ? '└─' : '├─';
    const labelPad = Math.max(0, 22 - prefix.length);
    lines.push(`  ${prefix}${connector} ${entry.label.padEnd(labelPad)} ${duration}`);
  }

  if (entry.children && entry.children.length > 0) {
    const childPrefix = indent === 0 ? '    ' : prefix + (isLast ? '   ' : '│  ');
    entry.children.forEach((child, i) => {
      const isChildLast = i === entry.children!.length - 1;
      lines.push(...formatEntry(child, indent + 1, isChildLast, childPrefix));
    });
  }

  return lines;
}

/**
 * Format a complete timing report
 */
export function formatTimingReport(report: TimingReport): string {
  const lines: string[] = [];

  lines.push('Timing Report');
  lines.push('─────────────');
  lines.push(`Total: ${formatDuration(report.total)}`);
  lines.push('');

  for (const entry of report.entries) {
    lines.push(...formatEntry(entry));
  }

  return lines.join('\n');
}

/**
 * Calculate statistics for a set of durations
 */
export function calculateStats(durations: number[]): Omit<BenchmarkResult, 'name' | 'iterations'> {
  const sorted = [...durations].sort((a, b) => a - b);
  const n = sorted.length;

  if (n === 0) {
    return { min: 0, max: 0, avg: 0, p50: 0, p95: 0, stdDev: 0 };
  }

  const min = sorted[0];
  const max = sorted[n - 1];
  const sum = sorted.reduce((a, b) => a + b, 0);
  const avg = sum / n;

  // Percentiles
  const p50Index = Math.floor(n * 0.5);
  const p95Index = Math.floor(n * 0.95);
  const p50 = sorted[Math.min(p50Index, n - 1)];
  const p95 = sorted[Math.min(p95Index, n - 1)];

  // Standard deviation
  const squaredDiffs = sorted.map((x) => Math.pow(x - avg, 2));
  const variance = squaredDiffs.reduce((a, b) => a + b, 0) / n;
  const stdDev = Math.sqrt(variance);

  return { min, max, avg, p50, p95, stdDev };
}

/**
 * Run a benchmark function multiple times and collect results
 */
export async function runBenchmark(
  name: string,
  fn: () => Promise<void>,
  options: { iterations?: number; warmup?: number } = {}
): Promise<BenchmarkResult> {
  const { iterations = 5, warmup = 1 } = options;
  const durations: number[] = [];

  // Warmup runs (not counted)
  for (let i = 0; i < warmup; i++) {
    await fn();
  }

  // Actual benchmark runs
  for (let i = 0; i < iterations; i++) {
    const timer = new Timer().start();
    await fn();
    timer.stop();
    durations.push(timer.elapsed());
  }

  const stats = calculateStats(durations);
  return {
    name,
    iterations,
    ...stats,
  };
}

/**
 * Format benchmark results as a table
 */
export function formatBenchmarkResults(results: BenchmarkResult[]): string {
  const lines: string[] = [];

  lines.push('Workspace Benchmark Results');
  lines.push('═══════════════════════════');
  lines.push('');

  // Header
  const header = 'Operation        │ Iter │    Min │    Max │    Avg │    P95';
  const separator = '─────────────────┼──────┼────────┼────────┼────────┼────────';
  lines.push(header);
  lines.push(separator);

  // Rows
  for (const result of results) {
    const name = result.name.padEnd(16);
    const iter = result.iterations.toString().padStart(4);
    const min = formatDuration(result.min).padStart(6);
    const max = formatDuration(result.max).padStart(6);
    const avg = formatDuration(result.avg).padStart(6);
    const p95 = formatDuration(result.p95).padStart(6);
    lines.push(`${name} │ ${iter} │ ${min} │ ${max} │ ${avg} │ ${p95}`);
  }

  return lines.join('\n');
}

/**
 * Global timing context (set when --timing flag is used)
 */
declare global {
  // eslint-disable-next-line no-var
  var __codiTimingContext: TimingContext | undefined;
}

/**
 * Get the global timing context if enabled
 */
export function getTimingContext(): TimingContext | undefined {
  return globalThis.__codiTimingContext;
}

/**
 * Set the global timing context
 */
export function setTimingContext(ctx: TimingContext | undefined): void {
  globalThis.__codiTimingContext = ctx;
}
