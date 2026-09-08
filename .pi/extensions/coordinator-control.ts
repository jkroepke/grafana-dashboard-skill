import { spawn } from "node:child_process";
import { resolve } from "node:path";

import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const MAX_OUTPUT_BYTES = 16 * 1024;
const SAFE_COMPONENT = /^[A-Za-z0-9._-]+$/;

const Action = StringEnum(
  ["mkworkspace", "set-workflow-env", "run-contract", "dispatch", "accept", "promote", "failure-report"] as const,
);

const OPERATIONS: Record<
  "mkworkspace" | "set-workflow-env" | "run-contract" | "dispatch" | "accept" | "promote" | "failure-report",
  { script: string; prefix: string[]; suffix?: string[] }
> = {
  mkworkspace: {
    script: "scripts/mkworkspace",
    prefix: [],
  },
  "set-workflow-env": {
    script: "scripts/set_workflow_env",
    prefix: [],
  },
  "run-contract": {
    script: "scripts/create_coordinator_artifact.py",
    prefix: ["run-contract"],
  },
  dispatch: {
    script: "scripts/coordinator_stage.py",
    prefix: ["dispatch"],
  },
  accept: {
    script: "scripts/coordinator_stage.py",
    prefix: ["accept"],
  },
  promote: {
    script: "scripts/verify_workflow_chain.py",
    prefix: [],
    suffix: ["--promote"],
  },
  "failure-report": {
    script: "scripts/create_coordinator_artifact.py",
    prefix: ["failure-report"],
  },
};

function appendBounded(
  chunks: Buffer[],
  chunk: Buffer,
  state: { size: number; overflow: boolean },
): void {
  if (state.overflow) return;
  state.size += chunk.length;
  if (state.size > MAX_OUTPUT_BYTES) {
    state.overflow = true;
    return;
  }
  chunks.push(chunk);
}

async function runOperation(
  action: keyof typeof OPERATIONS,
  args: string[],
  repositoryRoot: string,
  cwd: string,
  signal: AbortSignal,
): Promise<{ code: number; stdout: string; stderr: string; overflow: boolean }> {
  const operation = OPERATIONS[action];
  const script = resolve(repositoryRoot, operation.script);
  const argv = [script, ...operation.prefix, ...args, ...(operation.suffix ?? [])];

  return await new Promise((resolveResult) => {
    const child = spawn("python3", argv, {
      cwd,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
    });

    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];
    const stdoutState = { size: 0, overflow: false };
    const stderrState = { size: 0, overflow: false };

    child.stdout.on("data", (chunk: Buffer) => {
      appendBounded(stdoutChunks, chunk, stdoutState);
      if (stdoutState.overflow) child.kill("SIGTERM");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      appendBounded(stderrChunks, chunk, stderrState);
      if (stderrState.overflow) child.kill("SIGTERM");
    });

    const abort = () => child.kill("SIGTERM");
    signal.addEventListener("abort", abort, { once: true });

    child.on("error", (error) => {
      signal.removeEventListener("abort", abort);
      resolveResult({
        code: 1,
        stdout: "",
        stderr: `coordinator control failed to start: ${error.message}`,
        overflow: false,
      });
    });

    child.on("close", (code) => {
      signal.removeEventListener("abort", abort);
      resolveResult({
        code: code ?? 1,
        stdout: Buffer.concat(stdoutChunks).toString("utf8").trim(),
        stderr: Buffer.concat(stderrChunks).toString("utf8").trim(),
        overflow: stdoutState.overflow || stderrState.overflow,
      });
    });
  });
}

export default function coordinatorControlExtension(pi: ExtensionAPI): void {
  let workspaceCwd: string | undefined;

  pi.registerTool({
    name: "coordinator_control",
    label: "Coordinator Control",
    description:
      "Execute only deterministic coordinator-owned workflow operations. " +
      "It provides no general shell and invokes only fixed coordinator workflow entrypoints.",
    promptSnippet:
      "Use coordinator_control for coordinator-owned workflow execution; never fall back to bash.",
    promptGuidelines: [
      "coordinator_control is only for mkworkspace, set-workflow-env, run-contract, dispatch, accept, promote, and failure-report operations.",
      "Never use coordinator_control to reproduce specialist work or inspect specialist-owned content.",
    ],
    parameters: Type.Object({
      action: Action,
      arguments: Type.Array(
        Type.String({
          minLength: 1,
          maxLength: 2048,
          description: "One argv element passed to the fixed workflow operation.",
        }),
        {
          maxItems: 96,
          description:
            "Arguments for the selected fixed workflow operation. No shell parsing is performed.",
        },
      ),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      if (params.action !== "mkworkspace" && workspaceCwd === undefined) {
        return {
          content: [{ type: "text", text: `FAIL ${params.action}: run mkworkspace first` }],
          details: { action: params.action, exitCode: 2, overflow: false },
          isError: true,
        };
      }
      const result = await runOperation(
        params.action,
        params.arguments,
        ctx.cwd,
        params.action === "mkworkspace" ? ctx.cwd : workspaceCwd!,
        signal,
      );

      if (params.action === "mkworkspace" && result.code === 0 && !result.overflow) {
        const projectName = params.arguments.length === 1 ? params.arguments[0] : undefined;
        const expected = projectName && SAFE_COMPONENT.test(projectName)
          ? resolve(ctx.cwd, "dashboards", projectName, "workspace")
          : undefined;
        if (expected === undefined || result.stdout !== expected) {
          return {
            content: [{ type: "text", text: "FAIL mkworkspace: invalid workspace path" }],
            details: { action: params.action, exitCode: 1, overflow: false },
            isError: true,
          };
        }
        workspaceCwd = expected;
      }

      if (result.overflow) {
        return {
          content: [
            {
              type: "text",
              text: `FAIL ${params.action}: bounded coordinator output exceeded ${MAX_OUTPUT_BYTES} bytes`,
            },
          ],
          details: { action: params.action, exitCode: result.code, overflow: true },
          isError: true,
        };
      }

      const text =
        result.code === 0
          ? result.stdout || `PASS ${params.action}`
          : result.stderr || result.stdout || `FAIL ${params.action}`;

      return {
        content: [{ type: "text", text }],
        details: { action: params.action, exitCode: result.code, overflow: false },
        isError: result.code !== 0,
      };
    },
  });
}
