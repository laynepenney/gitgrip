import { spawn } from 'child_process';
import { resolve } from 'path';
import type { Manifest, WorkspaceScript, ScriptStep } from '../types.js';

export interface ScriptStepResult {
  name: string;
  command: string;
  cwd: string;
  success: boolean;
  exitCode: number | null;
  error?: string;
}

export interface ScriptResult {
  scriptName: string;
  success: boolean;
  steps: ScriptStepResult[];
}

/**
 * Run a single command (used for both single commands and steps)
 */
async function runCommand(
  command: string,
  cwd: string,
  env: Record<string, string>,
  onStdout?: (data: string) => void,
  onStderr?: (data: string) => void
): Promise<{ success: boolean; exitCode: number | null; error?: string }> {
  return new Promise((resolvePromise) => {
    const proc = spawn(command, [], {
      cwd,
      shell: true,
      stdio: ['inherit', 'pipe', 'pipe'],
      env: {
        ...process.env,
        ...env,
      },
    });

    proc.stdout?.on('data', (data) => {
      const str = data.toString();
      if (onStdout) {
        onStdout(str);
      } else {
        process.stdout.write(str);
      }
    });

    proc.stderr?.on('data', (data) => {
      const str = data.toString();
      if (onStderr) {
        onStderr(str);
      } else {
        process.stderr.write(str);
      }
    });

    proc.on('close', (exitCode) => {
      resolvePromise({
        success: exitCode === 0,
        exitCode,
      });
    });

    proc.on('error', (error) => {
      resolvePromise({
        success: false,
        exitCode: null,
        error: error.message,
      });
    });
  });
}

/**
 * Run a workspace script by name
 */
export async function runScript(
  scriptName: string,
  manifest: Manifest,
  rootDir: string,
  args: string[] = []
): Promise<ScriptResult> {
  const workspace = manifest.workspace;
  if (!workspace?.scripts) {
    throw new Error('No workspace scripts defined in manifest');
  }

  const script = workspace.scripts[scriptName];
  if (!script) {
    const available = Object.keys(workspace.scripts).join(', ');
    throw new Error(`Script '${scriptName}' not found. Available: ${available}`);
  }

  // Get workspace env
  const env = workspace.env ?? {};

  const result: ScriptResult = {
    scriptName,
    success: true,
    steps: [],
  };

  if (script.command) {
    // Single command script
    const cwd = script.cwd ? resolve(rootDir, script.cwd) : rootDir;

    // Append any extra args
    const fullCommand = args.length > 0 ? `${script.command} ${args.join(' ')}` : script.command;

    const stepResult = await runCommand(fullCommand, cwd, env);
    result.steps.push({
      name: scriptName,
      command: fullCommand,
      cwd,
      success: stepResult.success,
      exitCode: stepResult.exitCode,
      error: stepResult.error,
    });
    result.success = stepResult.success;
  } else if (script.steps) {
    // Multi-step script
    for (const step of script.steps) {
      const cwd = step.cwd ? resolve(rootDir, step.cwd) : rootDir;
      const stepResult = await runCommand(step.command, cwd, env);

      result.steps.push({
        name: step.name,
        command: step.command,
        cwd,
        success: stepResult.success,
        exitCode: stepResult.exitCode,
        error: stepResult.error,
      });

      if (!stepResult.success) {
        result.success = false;
        break;
      }
    }
  } else {
    throw new Error(`Script '${scriptName}' has neither command nor steps defined`);
  }

  return result;
}

/**
 * Get list of available scripts
 */
export function listScripts(manifest: Manifest): { name: string; description?: string }[] {
  const workspace = manifest.workspace;
  if (!workspace?.scripts) {
    return [];
  }

  return Object.entries(workspace.scripts).map(([name, script]) => ({
    name,
    description: script.description,
  }));
}
