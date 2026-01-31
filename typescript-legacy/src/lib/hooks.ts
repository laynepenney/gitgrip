import { spawn } from 'child_process';
import { resolve } from 'path';
import type { HookCommand } from '../types.js';

export interface HookResult {
  command: string;
  cwd: string;
  success: boolean;
  exitCode: number | null;
  stdout: string;
  stderr: string;
  error?: string;
}

/**
 * Run a single hook command
 */
export async function runHookCommand(
  hook: HookCommand,
  rootDir: string,
  env?: Record<string, string>
): Promise<HookResult> {
  const cwd = hook.cwd ? resolve(rootDir, hook.cwd) : rootDir;

  return new Promise((resolvePromise) => {
    const proc = spawn(hook.command, [], {
      cwd,
      shell: true,
      env: {
        ...process.env,
        ...env,
      },
    });

    let stdout = '';
    let stderr = '';

    proc.stdout?.on('data', (data) => {
      stdout += data.toString();
    });

    proc.stderr?.on('data', (data) => {
      stderr += data.toString();
    });

    proc.on('close', (exitCode) => {
      resolvePromise({
        command: hook.command,
        cwd,
        success: exitCode === 0,
        exitCode,
        stdout,
        stderr,
      });
    });

    proc.on('error', (error) => {
      resolvePromise({
        command: hook.command,
        cwd,
        success: false,
        exitCode: null,
        stdout,
        stderr,
        error: error.message,
      });
    });
  });
}

/**
 * Run a list of hook commands sequentially
 */
export async function runHooks(
  hooks: HookCommand[],
  rootDir: string,
  env?: Record<string, string>
): Promise<HookResult[]> {
  const results: HookResult[] = [];

  for (const hook of hooks) {
    const result = await runHookCommand(hook, rootDir, env);
    results.push(result);

    // Stop on first failure
    if (!result.success) {
      break;
    }
  }

  return results;
}
